# RAG UI Service - Quick Start Guide

## 🚀 Quick Start (5 minutes)

### Prerequisites
- Python 3.11+
- Docker (optional)
- RAG System running

### Option 1: Local Development

1. **Setup**
```bash
cd ui-service
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure**
```bash
cp .env.example .env
# Edit .env if using non-standard addresses
```

3. **Run**
```bash
uvicorn app.main:app --reload
# Open http://localhost:8000
```

### Option 2: Docker Compose

```bash
# From project root
docker-compose up ui-service

# Open http://localhost:8000
```

### Option 3: Standalone Docker

```bash
docker build -t rag-ui .
docker run -p 8000:8000 \
  --network rag-production_default \
  rag-ui
```

## 🎯 Features at a Glance

| Feature | How to Use |
|---------|-----------|
| **New Chat** | Click "New Chat" button in sidebar |
| **Upload Doc** | Click attachment icon or use file input |
| **Ask Question** | Type in input box, press Enter or click Send |
| **View Sources** | Click sources panel that appears after answers |
| **Switch Session** | Click session in sidebar to load history |
| **Theme Toggle** | Click moon/sun icon in top right |

## 📊 Key Endpoints

```bash
# Health check
curl http://localhost:8000/health

# Create session
curl -X POST http://localhost:8000/api/session/new

# Send question
curl -X POST http://localhost:8000/ask \
  -d "question=What is AI?" \
  -d "session_id=YOUR_SESSION_ID"

# Get documents
curl http://localhost:8000/api/documents

# Get services status
curl http://localhost:8000/api/services-status
```

## 🔧 Configuration Quick Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `LOG_LEVEL` | INFO | Console log level |
| `MAX_FILE_SIZE` | 50 | Max file size in MB |
| `REQUEST_TIMEOUT` | 300 | API timeout in seconds |
| `RAG_SERVICE_URL` | http://rag-service:8003 | RAG service address |
| `EMBEDDING_SERVICE_URL` | http://embedding-service:8001 | Vector DB address |

## 🎨 UI Components Overview

```
┌─ SIDEBAR ─────────────────┐
│  🧠 RAG AI                │
│  [+ New Chat]             │
│  Sessions:                │
│  • Session 1 (5 msgs)     │
│  • Session 2 (3 msgs)     │
│  Documents:               │
│  📄 document.pdf          │
│  Services:                │
│  🟢 RAG  🟢 Embedding     │
└───────────────────────────┘
┌─────────────── MAIN AREA ──────────────┐
│ Header: AI Knowledge Assistant    [🌙] │
├────────────────────────────────────────┤
│ Chat Messages (scrollable)             │
│                                        │
│ [User]: What is machine learning?     │
│ [AI]: Machine learning is...          │
│                                 📚 1 src│
├────────────────────────────────────────┤
│ [📎 Attach file] [Type question...] [→]│
│ [⏳ Processing...]                     │
└────────────────────────────────────────┘
```

## 🐛 Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| UI not loading | Check port 8000 is not blocked |
| Services show offline | Verify backend services are running |
| Upload fails | Check file size < 50MB and format supported |
| No answer received | Ensure RAG service is responding |

## 📈 Performance Tips

- **Browser:** Use Chrome/Firefox for best performance
- **Documents:** Keep under 10MB for faster processing
- **Sessions:** Archive old sessions to free memory
- **Network:** Ensure 100Mbps+ for optimal experience

## 🎓 Example Workflows

### Workflow 1: Knowledge Base Query
1. Upload PDF → Click "Attach file"
2. Wait for "Document uploaded" message
3. Ask questions → Type and press Enter
4. Review answers → Click sources panel

### Workflow 2: Research Session
1. Start new chat → Click "New Chat"
2. Upload multiple documents
3. Ask multi-part questions
4. Switch back to session anytime

### Workflow 3: Mobile Usage
1. Open on tablet/phone
2. Sidebar auto-collapses
3. Full screen chat area
4. Swipe for responsive layout

## 🔐 Security Notes

- **File Validation:** Server-side file type checking
- **Session IDs:** UUID format, cryptographically random
- **Input Sanitized:** HTML escaping on display
- **CORS:** Enabled for frontend requests
- **Size Limits:** 50MB max file size enforced

## 📞 Support Resources

- **Logs:** Check console with F12 in browser
- **Server Logs:** `docker logs rag-ui-service`
- **Status Page:** Visit `/api/services-status`
- **Health:** Check `/health` endpoint

## 🔄 Troubleshooting Commands

```bash
# Check service health
curl http://localhost:8000/health

# Verify backend connectivity
curl http://localhost:8000/api/services-status

# View server logs
docker logs -f rag-ui-service

# Restart service
docker-compose restart ui-service

# Clear session data (restart)
docker-compose down ui-service
docker-compose up ui-service
```

## 📝 Next Steps

1. ✅ UI Service running
2. ➡️ Upload your first document
3. ➡️ Ask a question
4. ➡️ Review the sources
5. ➡️ Start a new session
6. ➡️ Explore service status

## 🎉 You're ready to go!

Visit **http://localhost:8000** and start exploring!

---

For detailed documentation, see [README.md](README.md)
