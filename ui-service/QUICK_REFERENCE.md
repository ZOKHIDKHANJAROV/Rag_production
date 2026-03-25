# RAG UI Service - Quick Reference Guide

## 🚀 Quick Start

```bash
# Start all services
cd /path/to/rag-production
docker-compose up -d

# Wait 10-15 seconds, then open
http://localhost:8000
```

---

## 🎯 Common Commands

### Service Management

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# View running services
docker-compose ps

# View detailed logs
docker-compose logs -f

# Restart specific service
docker-compose restart ui-service

# View logs for specific service
docker logs ui-service
```

### Diagnostics

```bash
# Windows: Run diagnostic PowerShell script
.\diagnostic.ps1

# Linux/macOS: Run diagnostic bash script
bash diagnostic.sh

# Test RAG service directly
curl -X POST http://localhost:8003/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"test","session_id":"test"}'

# Test health of all services
curl http://localhost:8000/health
curl http://localhost:8003/health
curl http://localhost:8001/health
curl http://localhost:8004/health
```

### Configuration

```bash
# Edit environment variables
nano .env

# Copy template
cp example.env .env

# Apply changes (restart service)
docker-compose restart ui-service
```

### Development

```bash
# Run UI service locally (not Docker)
python -m uvicorn app.main:app --reload

# Install dependencies
pip install -r requirements.txt

# Run tests
python -m pytest tests/

# Check syntax
python -m py_compile app/*.py
```

---

## 🔧 Configuration Reference

### .env Variables

```env
# UI Service
PORT=8000
LOG_LEVEL=INFO

# Backend Services
RAG_SERVICE_URL=http://rag-service:8003/ask
EMBEDDING_SERVICE_URL=http://embedding-service:8001
INGESTION_SERVICE_URL=http://ingestion-service:8004/upload
LLM_SERVICE_URL=http://llm-service:8002

# Database
QDRANT_URL=http://qdrant:6333

# Request Handling
REQUEST_TIMEOUT=300
MAX_RETRIES=3

# File Upload
MAX_FILE_SIZE=50  # MB
```

### For Local Development (localhost)

Replace service URLs with:
```env
RAG_SERVICE_URL=http://localhost:8003/ask
EMBEDDING_SERVICE_URL=http://localhost:8001
INGESTION_SERVICE_URL=http://localhost:8004/upload
LLM_SERVICE_URL=http://localhost:8002
QDRANT_URL=http://localhost:6333
```

---

## 🌐 API Endpoints

### Chat API

```bash
# Ask a question
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is X?",
    "session_id": "session-123"
  }'

# Get chat history
curl http://localhost:8000/sessions/session-123

# Create new session
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json"

# Delete session
curl -X DELETE http://localhost:8000/sessions/session-123
```

### Health Checks

```bash
# UI Service health
curl http://localhost:8000/health

# Services status
curl http://localhost:8000/services/status

# Debug config
curl http://localhost:8000/api/debug/config

# Test RAG connection
curl -X POST http://localhost:8000/api/debug/test-rag \
  -H "Content-Type: application/json" \
  -d '{"question":"test"}'
```

### Document Upload

```bash
# Upload file
curl -X POST http://localhost:8000/documents/upload \
  -F "file=@/path/to/file.pdf"
```

---

## 📊 Service Architecture

```
UI Service (Port 8000)
├── FastAPI Backend
├── Session Management
├── Document Upload
└── Real-time Chat

├── RAG Service (Port 8003)
│   └── Question Answering
│
├── Embedding Service (Port 8001)
│   └── Vector Embeddings
│
├── Ingestion Service (Port 8004)
│   └── Document Processing
│
├── LLM Service (Port 8002)
│   └── Language Model
│
└── Qdrant (Port 6333)
    └── Vector Database
```

---

## 🐛 Error Codes

| Code | Meaning | Fix |
|------|---------|-----|
| 200 | ✅ Success |  |
| 400 | Bad request | Check JSON format |
| 502 | Service unavailable | Start backend services |
| 503 | Cannot connect | Check service URL in .env |
| 504 | Timeout | Increase REQUEST_TIMEOUT |
| 500 | Server error | Check logs: `docker logs` |

---

## 🔍 Debugging Checklist

```bash
# 1. Check services are running
docker-compose ps

# 2. Check logs for errors
docker logs ui-service
docker logs rag-service

# 3. Test RAG service directly
curl http://localhost:8003/health

# 4. Check configuration
cat .env

# 5. Test network connectivity
docker exec rag-ui ping rag-service

# 6. Restart everything
docker-compose down
docker-compose up -d

# 7. Run diagnostic
./diagnostic.ps1  # or diagnostic.sh
```

---

## 📁 Project Structure

```
ui-service/
├── app/
│   ├── main.py              # FastAPI application
│   ├── schemas.py           # Data models
│   ├── rag_core.py          # RAG logic
│   └── ...
├── templates/
│   └── chat.html            # Frontend UI
├── static/
│   ├── style.css            # Styling
│   └── ...
├── .env                     # Configuration
├── requirements.txt         # Dependencies
├── Dockerfile              # Container image
├── diagnostic.ps1          # Windows diagnostic
├── diagnostic.sh           # Linux/Mac diagnostic
├── TROUBLESHOOTING.md      # Error resolution
├── QUICKSTART.md           # Setup guide
├── README.md               # Full documentation
└── ARCHITECTURE.md         # System design
```

---

## 🔐 Ports Overview

| Service | Port | URL |
|---------|------|-----|
| UI Service | 8000 | http://localhost:8000 |
| RAG Service | 8003 | http://localhost:8003 |
| Embedding Service | 8001 | http://localhost:8001 |
| Ingestion Service | 8004 | http://localhost:8004 |
| LLM Service | 8002 | http://localhost:8002 |
| Qdrant | 6333 | http://localhost:6333 |
| Redis | 6379 | redis://localhost:6379 |

---

## 🎨 Theme & Preferences

The UI supports:
- **Dark Theme** (default) - Easier on eyes, better for long sessions
- **Light Theme** - High contrast
- **Auto-save settings** - Uses browser localStorage
- **Session persistence** - During browser session only

**Theme switch:** Click moon/sun icon top-left

---

## 📱 Responsive Design

- **Desktop**: Full sidebar + chat + services panel
- **Tablet**: Collapsible sidebar
- **Mobile**: Bottom navigation, stacked layout

All modern browsers supported:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

---

## 🚀 Performance Tips

1. **Increase timeout for large documents:**
   ```env
   REQUEST_TIMEOUT=600
   ```

2. **Upload smaller files** - Reduces processing time

3. **Create new sessions** - Clears memory

4. **Restart services regularly** - Frees memory

5. **Check system resources:**
   ```bash
   docker stats
   ```

---

## 📞 Useful Documentation

- [README.md](README.md) - Complete guide
- [QUICKSTART.md](QUICKSTART.md) - Setup instructions
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Error fixes
- [API Examples](api-examples.sh) / [Windows](api-examples.ps1) - API testing

---

## 🔄 Restart Sequence (When Everything Fails)

```bash
# 1. Stop everything
docker-compose down

# 2. Remove containers & volumes (clears data)
docker-compose down -v

# 3. Clean up images (optional)
docker system prune -a

# 4. Start fresh
docker-compose up -d

# 5. Wait 15 seconds
sleep 15

# 6. Verify
docker-compose ps

# 7. Open browser
http://localhost:8000
```

---

## 💾 Backup & Restore

### Backup Data

```bash
# Backup Qdrant data
docker cp qdrant:/qdrant/storage ./qdrant-backup

# Backup configuration
cp .env .env.backup
```

### Restore Data

```bash
# Restore Qdrant data
docker cp ./qdrant-backup qdrant:/qdrant/storage

# Restart service
docker-compose restart qdrant
```

---

## 🔐 Security Notes

⚠️ Default configuration is for **development only**

For production:
- [ ] Change default passwords
- [ ] Enable HTTPS
- [ ] Set up authentication
- [ ] Configure firewall rules
- [ ] Use environment secrets
- [ ] Enable CORS restrictions
- [ ] Set up rate limiting

---

## 🆘 Get Help

1. **Check TROUBLESHOOTING.md** - Most issues covered there
2. **Run diagnostic script** - Identifies problems quickly
3. **Check logs** - `docker logs [service-name]`
4. **Verify configuration** - `cat .env`
5. **Review ARCHITECTURE.md** - Understand system design

**Common issues quick fixes:**
- "Service offline" → Run `docker-compose up -d`
- "Cannot connect" → Check .env URLs
- "Timeout" → Increase REQUEST_TIMEOUT
- "Port in use" → Kill process or use different port

---

**Version:** 2.0.0  
**Updated:** 2024  
**Maintained by:** AI Assistant
