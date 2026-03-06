# RAG UI Service v2.0 - Project Structure & Navigation Guide

## 📦 Complete Project Structure

```
RAG-Production/ui-service/
│
├── 📄 SETUP_COMPLETE.md ⭐ 
│   └── Complete implementation summary (START HERE)
│
├── 📄 QUICKSTART.md ⚡
│   └── 5-minute setup guide
│
├── 📄 README.md 📖
│   └── Comprehensive documentation
│
├── 📄 ARCHITECTURE.md 🏗️
│   └── System design and data flows
│
├── 📄 IMPLEMENTATION.md 📝
│   └── What's new and technical details
│
├── 📄 .env.example 🔧
│   └── Environment configuration template
│
├── 📄 requirements.txt 📦
│   └── Python dependencies
│
├── 📄 Dockerfile 🐋
│   └── Container configuration
│
├── 📄 api-examples.sh 🔌
│   └── Bash/Linux API testing script
│
├── 📄 api-examples.ps1 🔌
│   └── PowerShell/Windows API testing script
│
├── 📁 app/
│   ├── __init__.py
│   │   └── Package initialization
│   │
│   └── main.py ✨ (450+ lines)
│       ├── FastAPI application setup
│       ├── Session management (CRUD operations)
│       ├── Chat endpoints (/ask, /upload)
│       ├── Service monitoring (/api/services-status)
│       ├── Health checks
│       └── Error handling & logging
│
├── 📁 templates/
│   └── chat.html ✨ (600+ lines)
│       ├── Sidebar with sessions management
│       ├── Document list & upload
│       ├── Service status indicators
│       ├── Chat message display area
│       ├── Sources attribution panel
│       ├── Input section with text & file
│       ├── Theme toggle button
│       ├── JavaScript (500+ lines)
│       │   ├── Session management
│       │   ├── Chat functionality
│       │   ├── File upload handling
│       │   ├── Service status monitoring
│       │   ├── Theme management
│       │   └── UI interactions
│       └── Responsive design for all devices
│
└── 📁 static/
    └── style.css ✨ (520+ lines)
        ├── CSS Variables for theming
        ├── Light theme colors (white background)
        ├── Dark theme colors (dark blue background)
        ├── Layout styles (Flexbox/Grid)
        ├── Component styles (buttons, inputs, messages)
        ├── Responsive design rules
        ├── Animations & transitions
        ├── Scrollbar styling
        └── Mobile breakpoints
```

## 📊 File Statistics

| File | Lines | Purpose |
|------|-------|---------|
| app/main.py | 450+ | Backend API |
| templates/chat.html | 600+ | Frontend UI + JS |
| static/style.css | 520+ | Styling |
| README.md | 300+ | Documentation |
| ARCHITECTURE.md | 300+ | Design docs |
| QUICKSTART.md | 200+ | Setup guide |
| IMPLEMENTATION.md | 250+ | Summary |
| **TOTAL** | **2,600+** | All code & docs |

## 🚀 Getting Started Guide

### Step 1: Choose Your Path

```
┌─────────────────────────────────────┐
│  Read SETUP_COMPLETE.md first! ⭐   │
└──────────────┬──────────────────────┘
               │
     ┌─────────┴──────────┬──────────────────┐
     │                    │                  │
     ▼                    ▼                  ▼
  Quick Start        Deep Dive           Testing
  (5 min)            (30 min)            (10 min)
     │                    │                  │
     ▼                    ▼                  ▼
QUICKSTART.md      ARCHITECTURE.md    api-examples.sh
     │                    │                  │
     ▼                    ▼                  ▼
Run locally         Understand design   Test APIs
```

### Step 2: Install & Run

```bash
# 1. Setup environment
cd ui-service
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure (optional)
cp .env.example .env
# Edit .env if needed

# 4. Run
uvicorn app.main:app --reload

# 5. Access
# Open http://localhost:8000 in your browser
```

### Step 3: Explore Features

```
┌─ Sidebar ────────────────────┐
├─ [+ New Chat]               │
├─ Sessions:                 │
│  • Session 1 (5 messages)  │
│  • Session 2 (3 messages)  │
├─ Documents:                │
│  📄 document.pdf (10 chk)  │
└─ Services: 🟢🟢🟢🟢        │
└──────────────────────────────┘
            ↓
┌─────────────────────────────────────────┐
│  AI Knowledge Assistant         [🌙][🔄] │ (Header)
├─────────────────────────────────────────┤
│  Chat Messages                          │
│  ┌──────────────────────────────────┐  │
│  │ [User]: What is AI?              │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │ [AI]: AI stands for...      📚1s │  │
│  └──────────────────────────────────┘  │
├─────────────────────────────────────────┤
│ [📎 Attach] [Ask a question...   ] [→]  │
│ [⏳ Processing...]               
└─────────────────────────────────────────┘
            ↓
┌─ Sources Panel ──────────────┐
│ 📚 Document.pdf      90% ✓   │
│ "Text excerpt about AI..."   │
│ 📚 Another.doc       85%     │
│ "More relevant text..."      │
└──────────────────────────────┘
```

## 🎯 Feature Navigation

### Chat & Messaging
1. **Ask Question** → Type in input box → Press Enter
2. **View Sources** → Click "📚 N sources" → See attribution
3. **Upload Docs** → Click "📎" → Select file → Wait for upload
4. **Clear Chat** → Click "New Chat" → Start fresh

### Session Management
1. **New Session** → Click "+ New Chat" button
2. **Switch Session** → Click any session in sidebar
3. **Delete Session** → Click "×" button on session
4. **View History** → Click session to load messages

### Document Management
1. **View Documents** → Check Documents panel
2. **Upload Document** → Click attachment icon
3. **See Metadata** → Chunks count shown
4. **Track Documents** → All uploads per session

### System Monitoring
1. **Check Services** → See indicators in Services panel
2. **Refresh Status** → Click 🔄 button
3. **Health Check** → Visit /health endpoint
4. **View Details** → Check /api/services-status

### Appearance
1. **Toggle Theme** → Click moon/sun icon
2. **Switch Modes** → Dark ↔️ Light
3. **Persist Theme** → Auto-saved locally

## 📱 Responsive Design

```
Desktop (1024px+)          Tablet (640-1024px)     Mobile (< 640px)
┌──────────┬────────┐      ┌─────────────────┐     ┌───────────┐
│          │        │      │  Sidebar        │     │ Sidebar   │
│ Sidebar  │ Chat   │      │ (horizontal)    │     │ (horiz)   │
│  280px   │ Main   │      │                 │     │           │
│          │        │      │ Chat Area       │     │ Chat Area │
│          │        │      │ (full width)    │     │ (full)    │
└──────────┴────────┘      └─────────────────┘     └───────────┘
```

## 🔧 Configuration Guide

### Environment Variables Location: `.env`

```env
# Logging
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR

# File Upload
MAX_FILE_SIZE=50            # In MB

# Backend Services
RAG_SERVICE_URL=            # RAG system
INGESTION_SERVICE_URL=      # Document ingestion
EMBEDDING_SERVICE_URL=      # Vector database
LLM_SERVICE_URL=           # Language model
QDRANT_URL=                # Vector storage

# Server
REQUEST_TIMEOUT=300        # Seconds
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
```

## 🧪 Testing Guides

### Browser Testing
1. Open DevTools (F12)
2. Check Console tab for JavaScript logs
3. Check Network tab for API calls
4. Try all features manually
5. Test on mobile viewport

### API Testing

#### Using Bash (Linux/macOS)
```bash
bash api-examples.sh
```

#### Using PowerShell (Windows)
```powershell
.\api-examples.ps1
```

#### Using curl
```bash
# Create session
curl -X POST http://localhost:8000/api/session/new

# Ask question
curl -X POST http://localhost:8000/ask \
  -d "question=What is RAG?" \
  -d "session_id=YOUR_SESSION_ID"

# Get services status
curl http://localhost:8000/api/services-status
```

## 📚 Documentation Navigation

```
START HERE
    ↓
SETUP_COMPLETE.md ────→ Implementation Summary
    ↓
QUICKSTART.md ────────→ 5-minute Setup
    ↓
README.md ────────────→ Full Reference
    ├─ Features
    ├─ Installation
    ├─ API Reference
    ├─ Environment Variables
    ├─ Troubleshooting
    └─ Contributing
    
ARCHITECTURE.md ───────→ Deep Dive
    ├─ System Design
    ├─ Request Flow
    ├─ Data Structures
    ├─ Performance
    └─ Scaling

IMPLEMENTATION.md ─────→ Technical Details
    ├─ What's New
    ├─ Specifications
    ├─ Testing
    └─ Development
```

## 🔍 Code Navigation

### Backend Logic (app/main.py)

```python
# 1. Imports & Setup (Lines 1-50)
# 2. Configuration (Lines 51-100)
# 3. Session Management (Lines 101-200)
# 4. Health & Monitoring (Lines 201-250)
# 5. Chat Operations (Lines 251-350)
# 6. File Upload (Lines 351-400)
# 7. Documents & Sessions (Lines 401-450)
```

### Frontend Logic (templates/chat.html)

```html
<!-- 1. HTML Structure (Lines 1-150) -->
<!-- 2. JavaScript Configuration (Lines 150-200) -->
<!-- 3. State Management (Lines 200-250) -->
<!-- 4. Theme Toggle (Lines 250-280) -->
<!-- 5. Session Management (Lines 280-350) -->
<!-- 6. Chat Operations (Lines 350-450) -->
<!-- 7. UI Helpers (Lines 450-550) -->
<!-- 8. Utilities (Lines 550-600) -->
```

### Styling (static/style.css)

```css
/* 1. Variables & Reset (Lines 1-50) */
/* 2. Sidebar (Lines 51-150) */
/* 3. Main Content (Lines 151-250) */
/* 4. Chat Area (Lines 251-350) */
/* 5. Input Section (Lines 351-450) */
/* 6. Toast & Utilities (Lines 451-520) */
```

## ⚡ Quick Reference

### Most Common Tasks

| Task | How To |
|------|--------|
| Start app | `uvicorn app.main:app --reload` |
| Create session | Click "+ New Chat" |
| Upload document | Click "📎" & select file |
| Ask question | Type & press Enter |
| Toggle theme | Click 🌙/☀️ icon |
| Switch session | Click session in sidebar |
| View sources | Click "📚 N sources" |
| Check services | See green dots in sidebar |
| Clear all sessions | Restart the server |
| Edit config | Edit `.env` file |

## 🚨 Troubleshooting Quick Links

| Problem | Solution |
|---------|----------|
| 404 Not Found | Check port 8000 is accessible |
| Services offline | Start backend services |
| Upload fails | Check file size & format |
| No answer | Verify RAG service running |
| Slow responses | Check network bandwidth |
| Theme not working | Clear browser cache |

## 📞 Help Resources

```
Issue?
    ↓
Check QUICKSTART.md
    ├─ Common Issues section
    ├─ Troubleshooting commands
    └─ FAQ
    ↓
If still stuck?
    ├─ Check browser console (F12)
    ├─ Check server logs
    ├─ Run api-examples
    └─ Read ARCHITECTURE.md
```

## ✅ Verification Checklist

After setup, verify these work:

- [ ] UI loads at http://localhost:8000
- [ ] Can create new session
- [ ] Can upload a document
- [ ] Can ask a question
- [ ] Sees answer with sources
- [ ] Theme toggle works
- [ ] Service status shown
- [ ] Can switch sessions
- [ ] Can delete session
- [ ] Sidebar shows history

## 🎉 You're Ready!

```
Setup Complete! ✅
     ↓
Documentation Read ✅
     ↓
Features Explored ✅
     ↓
APIs Tested ✅
     ↓
Ready to Use! 🚀
```

---

## Next Steps

1. **Try It** - http://localhost:8000
2. **Upload** - Test with a sample document
3. **Ask** - Try asking questions about it
4. **Explore** - Check all features
5. **Customize** - Adapt to your needs

**Questions?** Check [README.md](README.md) for detailed documentation.

**Happy chatting!** 🚀
