# RAG UI Service - Troubleshooting Guide

## ❌ Error: "Sorry, I encountered an error. Please try again."

This is the most common error. Follow these steps to fix it:

### Step 1: Run Diagnostic Script

**Windows (PowerShell):**
```powershell
.\diagnostic.ps1
```

**Linux/macOS (Bash):**
```bash
bash diagnostic.sh
```

This will show what's actually wrong.

### Step 2: Common Causes & Solutions

#### 🔴 **RAG Service - OFFLINE**

**Problem:** The RAG service is not running or unreachable.

**Solutions:**

1. **Check if RAG service is running:**
```bash
docker ps | grep rag-service
```

If not shown, start it:
```bash
docker-compose up rag-service -d
```

2. **Check RAG service logs:**
```bash
docker logs -f rag-service
```

Look for errors like:
- Connection errors to other services
- Port conflicts
- Missing dependencies

3. **Verify RAG service is healthy:**
```bash
curl http://rag-service:8003/health
```

Should return: `{"status":"ok"}`

4. **Check if you're using localhost deployment:**

If RAG service is running on your machine (not in Docker), you need to:

Edit `.env`:
```env
RAG_SERVICE_URL=http://localhost:8003/ask
```

Instead of:
```env
RAG_SERVICE_URL=http://rag-service:8003/ask
```

---

#### 🔴 **Embedding Service - OFFLINE**

**Problem:** Vector database connection failed.

**Solutions:**

1. **Check Qdrant (vector database) is running:**
```bash
docker ps | grep qdrant
```

2. **Check Embedding service:**
```bash
docker ps | grep embedding
```

3. **Start all services:**
```bash
docker-compose up -d
```

4. **Test Qdrant connection:**
```bash
curl http://localhost:6333/health
```

---

#### 🔴 **Ingestion Service - OFFLINE**

**Problem:** Document upload not working.

**Solutions:**

1. **Check if service is running:**
```bash
docker ps | grep ingestion
```

2. **Start it:**
```bash
docker-compose up ingestion-service -d
```

3. **Test endpoint:**
```bash
curl http://localhost:8004/health
```

---

#### 🔴 **Connection Refused / Cannot Connect**

**Problem:** UI Service cannot reach backend services.

**Solutions:**

1. **Check network connectivity:**
```bash
# From UI service container
docker exec rag-ui ping rag-service
```

2. **Verify .env configuration:**
```bash
cat .env
```

Check these variables:
- `RAG_SERVICE_URL` - Points to correct host:port
- `EMBEDDING_SERVICE_URL` - Correct URL
- `INGESTION_SERVICE_URL` - Correct URL

3. **For local development (localhost):**
```env
RAG_SERVICE_URL=http://localhost:8003/ask
EMBEDDING_SERVICE_URL=http://localhost:8001
INGESTION_SERVICE_URL=http://localhost:8004/upload
LLM_SERVICE_URL=http://localhost:8002
QDRANT_URL=http://localhost:6333
```

4. **For Docker Compose deployment:**
```env
RAG_SERVICE_URL=http://rag-service:8003/ask
EMBEDDING_SERVICE_URL=http://embedding-service:8001
INGESTION_SERVICE_URL=http://ingestion-service:8004/upload
LLM_SERVICE_URL=http://llm-service:8002
QDRANT_URL=http://qdrant:6333
```

---

## ❌ Error: "Cannot connect to RAG service"

**Cause:** Network issue or wrong URL.

**Fix:**

1. Copy correct URL to `.env`
2. Restart UI service:
```bash
docker-compose restart ui-service
```

3. Test manually:
```bash
curl -X POST http://RAG_URL/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"test","session_id":"test"}'
```

---

## ❌ Error: "RAG service timeout"

**Cause:** Service is slow or hanging.

**Fix:**

1. **Increase timeout in .env:**
```env
REQUEST_TIMEOUT=600
```

2. **Restart UI service:**
```bash
docker-compose restart ui-service
```

3. **Check RAG service logs:**
```bash
docker logs rag-service
```

4. **Restart RAG service if needed:**
```bash
docker-compose restart rag-service
```

---

## ❌ UI Service Won't Start

**Error:** "Port 8000 already in use" or similar

**Solutions:**

1. **Find process using port 8000:**

Windows:
```powershell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

Linux/macOS:
```bash
lsof -ti:8000 | xargs kill -9
```

2. **Use different port:**
```bash
uvicorn app.main:app --port 8001
```

3. **Check if another service is using it:**
```bash
docker ps
```

---

## ❌ File Upload Fails

**Error:** "File too large" or upload doesn't work

**Solutions:**

1. **Check file size:**
```bash
# Max file size is set in .env
MAX_FILE_SIZE=50  # MB
```

2. **Increase if needed:**
```env
MAX_FILE_SIZE=100
```

3. **Verify file format is supported:**
- ✅ PDF
- ✅ TXT
- ✅ DOCX
- ✅ markdown (.md)

4. **Check Ingestion service logs:**
```bash
docker logs ingestion-service
```

---

## ❌ No Response from Questions

**Problem:** Question sent but no answer appears

**Solutions:**

1. **Check browser console (F12) → Console tab:**
   - Look for JavaScript errors
   - Check network requests

2. **Check server logs:**
```bash
docker logs ui-service
```

3. **Look for timeout errors:**
   - May need to increase `REQUEST_TIMEOUT`
   - Check if RAG service is processing slowly

4. **Try diagnostic endpoint:**
```bash
curl http://localhost:8000/api/debug/test-rag
```

---

## ❌ Service Status Shows All Red (Offline)

**Problem:** All services appear offline in UI

**Solutions:**

1. **Ensure Docker Compose is running:**
```bash
cd /path/to/rag-production
docker-compose up -d
```

2. **Wait 10-15 seconds for services to start**

3. **Check all services are running:**
```bash
docker-compose ps
```

Expected: All services should have Status "Up"

4. **Refresh UI page** (Ctrl+R or Cmd+R)

5. **Click service refresh button** (🔄) in UI header

---

## ❌ Theme Toggle Not Working

**Problem:** Dark/Light theme not switching

**Solutions:**

1. **Clear browser cache:**
   - Chrome/Edge: Ctrl+Shift+Delete
   - Firefox: Ctrl+Shift+Delete
   - Safari: Cmd+Y

2. **Check localStorage is enabled:**
   - F12 → Application → Local Storage
   - Should have entry for darkMode

3. **Try different browser**

---

## ❌ Session Not Saving

**Problem:** Chat history disappears after refresh

**Solutions:**

1. **This is normal** - Sessions are in-memory only
   - They persist during current browser session
   - Clear on server restart

2. **To persist sessions, add Redis:**
   - Fork a new session or restart server

3. **Copy chat text before losing it**

---

## ⚠️ Slow Responses

**Problem:** Answers take very long time

**Solutions:**

1. **Increase timeout:**
```env
REQUEST_TIMEOUT=600
```

2. **Check RAG service is healthy:**
```bash
docker logs -f rag-service
```

3. **Check system resources:**
```bash
docker stats
```

4. **Reduce document size** or number of embeddings

---

## ⚠️ High Memory Usage

**Problem:** Services consuming lots of memory

**Solutions:**

1. **Check which service:**
```bash
docker stats
```

2. **Restart problematic service:**
```bash
docker-compose restart [service-name]
```

3. **Clear old sessions** (requires code change or restart)

4. **Check document size** - Very large documents use more memory

---

## 🔍 Detailed Debugging

### Enable Debug Logging

**Edit .env:**
```env
LOG_LEVEL=DEBUG
```

**Restart service:**
```bash
docker-compose restart ui-service
```

**Check detailed logs:**
```bash
docker logs ui-service | grep -i error
```

### Test Each Service Individually

```bash
# UI Service
curl http://localhost:8000/health

# RAG Service
curl http://localhost:8003/health

# Embedding Service
curl http://localhost:8001/health

# Ingestion Service  
curl http://localhost:8004/health

# Qdrant
curl http://localhost:6333/health
```

### Full Stack Restart

```bash
cd /path/to/rag-production

# Stop everything
docker-compose down

# Remove volumes (clears data)
docker-compose down -v

# Start fresh
docker-compose up -d

# Wait 15 seconds for services to start
sleep 15

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

---

## 🆘 Still Not Working?

1. **Collect information:**
   - Run: `docker-compose ps`
   - Run: `docker logs [service-name]`
   - Run: `./diagnostic.ps1` or `./diagnostic.sh`

2. **Check documentation:**
   - [README.md](README.md)
   - [QUICKSTART.md](QUICKSTART.md)
   - [ARCHITECTURE.md](ARCHITECTURE.md)

3. **Verify setup:**
   - All services in docker-compose.yml running
   - Correct .env configuration
   - Port 8000 not blocked
   - Sufficient disk space

4. **Try fresh deployment:**
   ```bash
   docker-compose down -v
   docker-compose up -d
   ```

5. **Check service logs for specific errors:**
   ```bash
   docker-compose logs -f
   ```

---

## 📋 Quick Checklist

- [ ] UI Service running at http://localhost:8000
- [ ] Can load home page without 404
- [ ] Services status shows at least one green indicator
- [ ] Can click "+ New Chat" and create session
- [ ] RAG service shows as healthy in services panel
- [ ] Diagnostic script shows "RAG Service is working"
- [ ] Can send test question without error

If all checks pass but still getting errors:
1. Check browser console (F12)
2. Check server logs: `docker logs ui-service`
3. Check RAG service logs: `docker logs rag-service`

---

## 📞 Getting More Help

**See also:**
- `QUICKSTART.md` - Setup help
- `README.md` - Complete documentation
- `ARCHITECTURE.md` - System design
- `api-examples.sh/ps1` - API testing

**Run diagnostic:**
- Windows: `.\diagnostic.ps1`
- Linux/Mac: `bash diagnostic.sh`

---

**Last Updated:** 2024  
**Version:** 2.0.0
