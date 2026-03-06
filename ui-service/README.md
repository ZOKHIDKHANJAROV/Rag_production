# RAG System UI Service

Modern web interface for the RAG (Retrieval-Augmented Generation) production system.

## Features

### 🎨 Modern User Interface
- **Dark/Light Theme Toggle** - Switch between dark and light modes
- **Responsive Design** - Works on desktop, tablet, and mobile devices
- **Real-time Chat** - Interactive conversation with AI assistant
- **Session Management** - Create, switch, and delete chat sessions

### 📚 Document Management
- **Document Upload** - Upload documents (PDF, TXT, DOCX, MD)
- **Document List** - View all uploaded documents
- **Chunk Tracking** - See how many chunks each document is split into
- **File Validation** - Auto-validate file size (max 50MB)

### 🔍 Advanced Features
- **Source Attribution** - View sources used for each answer with relevance scores
- **Chat History** - Persistent conversation history per session
- **Service Status** - Real-time monitoring of backend services
- **Session History** - Browse and restore previous conversations

### 🚀 Performance
- **Fast API** - Built with FastAPI for high performance
- **Optimized Frontend** - Vanilla JavaScript (no heavy frameworks)
- **Async Processing** - Non-blocking uploads and queries
- **Session Caching** - All sessions stored in memory for quick access

## Project Structure

```
ui-service/
├── app/
│   └── main.py           # FastAPI application
├── static/
│   └── style.css         # Modern CSS styling
├── templates/
│   └── chat.html         # Main interface
├── requirements.txt      # Python dependencies
├── Dockerfile            # Container configuration
├── .env.example          # Environment variables template
└── README.md             # This file
```

## Installation

### Local Development

1. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set environment variables**
```bash
cp .env.example .env
# Edit .env with your settings
```

4. **Run the application**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Visit `http://localhost:8000` in your browser.

### Docker Deployment

Build and run in Docker:

```bash
docker build -t rag-ui-service .
docker run -p 8000:8000 \
  --env RAG_SERVICE_URL=http://rag-service:8003/ask \
  --env INGESTION_SERVICE_URL=http://ingestion-service:8004/upload \
  --env EMBEDDING_SERVICE_URL=http://embedding-service:8001 \
  rag-ui-service
```

### Docker Compose

Use the main compose file:

```bash
docker-compose up ui-service
```

## API Endpoints

### Chat & Questions
- `POST /ask` - Ask a question
- `POST /upload` - Upload a document

### Session Management
- `POST /api/session/new` - Create new session
- `GET /api/session/{session_id}` - Get session details
- `GET /api/session/{session_id}/history` - Get chat history
- `DELETE /api/session/{session_id}` - Delete session
- `GET /api/sessions` - List all sessions

### Documents & System
- `GET /api/documents` - Get uploaded documents
- `GET /api/services-status` - Get services health status
- `GET /health` - Health check

## Environment Variables

```bash
# Logging level
LOG_LEVEL=INFO

# Maximum file size in MB
MAX_FILE_SIZE=50

# Backend service URLs
RAG_SERVICE_URL=http://rag-service:8003/ask
INGESTION_SERVICE_URL=http://ingestion-service:8004/upload
EMBEDDING_SERVICE_URL=http://embedding-service:8001
LLM_SERVICE_URL=http://llm-service:8002
QDRANT_URL=http://qdrant:6333

# Request timeout in seconds
REQUEST_TIMEOUT=300

# Server configuration
UVICORN_HOST=0.0.0.0
UVICORN_PORT=8000
```

## Frontend Features

### Components

**Sidebar**
- Logo and branding
- New chat button
- Recent sessions list with quick access
- Uploaded documents list
- Service status indicators

**Main Chat Area**
- Message display with user/AI differentiation
- Automatic scroll to latest message
- Empty state with welcome message
- Real-time message rendering

**Input Section**
- File upload with drag-and-drop ready
- Question input with Enter to send
- Send button with visual feedback
- Upload progress indicator
- Loading indicator during processing

**Sources Panel**
- Displays sources for each answer
- Shows relevance score percentage
- Source text preview
- Collapsible panel design

**Header**
- Application title
- Theme toggle button
- Service refresh button

### Theme Support

The application supports automatic theme switching:
- **Light Mode** - Clean white interface for bright environments
- **Dark Mode** - Dark interface for reduced eye strain

Theme preference is saved in `localStorage` and persists across sessions.

## Styling

The CSS uses modern features:
- **CSS Variables** - Easy theme customization
- **Flexbox & Grid** - Responsive layout
- **CSS Animations** - Smooth transitions
- **Media Queries** - Mobile-friendly design

### Color Scheme

**Light Theme**
- Background: White
- Text: Dark gray
- Primary: Blue (#3b82f6)
- Borders: Light gray

**Dark Theme**
- Background: Very dark blue (#0f172a)
- Text: Light gray
- Primary: Blue (#3b82f6)
- Borders: Dark gray

## JavaScript Features

### Session Management
- Create new sessions
- Switch between sessions
- Delete sessions
- Load session history
- Auto-save messages

### File Handling
- File size validation
- Supported formats: PDF, TXT, DOCX, MD
- Upload progress tracking
- Error handling and user feedback

### API Integration
- Fetch API for async requests
- FormData for file uploads
- JSON parsing and handling
- Error handling with toast notifications

### UI Interactions
- Toast notifications for feedback
- Loading indicators
- Smooth animations
- Responsive button feedback
- Keyboard shortcuts (Enter to send)

## Browser Compatibility

- Chrome/Edge: Latest
- Firefox: Latest
- Safari: Latest
- Mobile browsers: iOS Safari, Chrome Mobile

## Performance Tips

1. **Document Size** - Keep documents under 10MB for best performance
2. **Number of Sessions** - Archive old sessions to keep memory usage low
3. **Browser Cache** - Clear cache if experiencing issues
4. **Network** - Ensure stable connection to backend services

## Troubleshooting

### Services showing as "offline"
- Check if backend services are running
- Verify network connectivity
- Check firewall settings
- Ensure correct service URLs in environment

### Documents not appearing
- Ensure ingestion service is running
- Check document upload permissions
- Verify file format is supported
- Check file size is under limit

### Messages not sending
- Check RAG service is running
- Verify question is not empty
- Check network connection
- Look at browser console for errors

### Upload failures
- Verify file size is under 50MB
- Check file format is supported (.pdf, .txt, .doc, .docx, .md)
- Ensure ingestion service is accessible
- Check disk space on server

## Development

### Adding Custom Styles
1. Edit `static/style.css`
2. Use CSS variables for colors and sizing
3. Test on mobile viewports
4. Follow BEM naming convention

### Adding New Endpoints
1. Add route in `app/main.py`
2. Update JavaScript fetch calls in `templates/chat.html`
3. Handle responses and errors
4. Test with browser dev tools

### Debugging
1. Check browser console (F12)
2. Check server logs
3. Use network tab to inspect requests
4. Test endpoints with curl or Postman

## Contributing

1. Follow PEP 8 style guide for Python
2. Use semantic HTML in templates
3. Keep CSS organized by sections
4. Test on multiple browsers
5. Document changes in commit messages

## License

Same as main RAG System project

## Support

For issues or questions:
1. Check troubleshooting section
2. Review error logs
3. Check backend service status
4. Contact development team
