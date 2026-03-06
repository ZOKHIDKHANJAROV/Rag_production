# RAG UI Service Architecture

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CLIENT BROWSER                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  HTML5 + CSS3 + Modern JavaScript                   │  │
│  │  - Session Management                               │  │
│  │  - Real-time Chat                                   │  │
│  │  - Dark/Light Theme Toggle                          │  │
│  │  - File Upload with Progress                        │  │
│  │  - Service Status Monitor                           │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────┬──────────────────────────────────────────┘
                  │ HTTP/REST
                  ↓
┌─────────────────────────────────────────────────────────────┐
│            UI SERVICE (Port 8000)                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ FastAPI Application                                 │  │
│  │                                                      │  │
│  │ Endpoints:                                          │  │
│  │  •  POST /ask                                       │  │
│  │  •  POST /upload                                    │  │
│  │  •  POST /api/session/new                           │  │
│  │  •  GET  /api/session/{id}                          │  │
│  │  •  GET  /api/session/{id}/history                  │  │
│  │  •  DELETE /api/session/{id}                        │  │
│  │  •  GET  /api/sessions                              │  │
│  │  •  GET  /api/documents                             │  │
│  │  •  GET  /api/services-status                       │  │
│  │  •  GET  /health                                    │  │
│  │                                                      │  │
│  │ Components:                                         │  │
│  │  • Session Manager (in-memory storage)              │  │
│  │  • Request Router                                   │  │
│  │  • Error Handler                                    │  │
│  │  • Health Monitor                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────┬─────────────────────────────────────────┬────────┘
          │                                         │
    HTTP │                                         │ HTTP
          ↓                                         ↓
┌──────────────────────────┐    ┌──────────────────────────┐
│   RAG SERVICE            │    │ INGESTION SERVICE        │
│   (Port 8003)            │    │ (Port 8004)              │
│                          │    │                          │
│ • Ask questions          │    │ • Process documents      │
│ • Re-ranking             │    │ • Extract text           │
│ • Context retrieval      │    │ • Chunk splitting        │
│ • Answer generation      │    │ • Vector embedding       │
└─────────┬────────────────┘    └──────────┬───────────────┘
          │                                 │
          └────────────────┬────────────────┘
                           │
                           ↓
            ┌──────────────────────────────────┐
            │  EMBEDDING SERVICE (Port 8001)   │
            │                                  │
            │ • Vector embeddings              │
            │ • Similarity search              │
            │ • Collection management          │
            └─────────┬────────────────────────┘
                      │
                      ↓
            ┌──────────────────────────────────┐
            │  QDRANT (Vector DB)              │
            │                                  │
            │ • Vector storage                 │
            │ • Semantic search                │
            │ • Payload storage                │
            └──────────────────────────────────┘

Additional:
├─ LLM SERVICE (Port 8002) - Language model inference
├─ REDIS - Caching and session management
└─ PROMETHEUS - Metrics and monitoring
```

## Request Flow

### 1. Ask Question Flow
```
User Input (Question)
    ↓
Frontend sends POST /ask
    ↓
UI Service validates input
    ↓
UI Service calls RAG Service
    ↓
RAG Service:
  • Embeds question
  • Searches Vector DB
  • Re-ranks results
  • Generates answer
    ↓
Response with answer + sources
    ↓
Frontend displays answer
    ↓
Sources panel shows references
```

### 2. Upload Document Flow
```
User selects file
    ↓
Frontend validates (size, type)
    ↓
Frontend sends POST /upload
    ↓
UI Service validates on server
    ↓
UI Service calls Ingestion Service
    ↓
Ingestion Service:
  • Extracts text
  • Chunks document
  • Embeds chunks
  • Stores in Vector DB
    ↓
Response with status
    ↓
Frontend shows confirmation
    ↓
Document appears in list
```

### 3. Session Management Flow
```
New Chat button clicked
    ↓
Frontend calls POST /api/session/new
    ↓
UI Service creates session (UUID)
    ↓
Session stored in memory
    ↓
Frontend gets session_id
    ↓
All subsequent questions use session_id
    ↓
History automatically tracked
```

## Data Structures

### Session Object
```python
{
    "session_id": "uuid-string",
    "created": "ISO-8601 timestamp",
    "history": [
        {
            "type": "question|answer|system|error",
            "content": "message text",
            "sources": [...],  # for answers
            "timestamp": "ISO-8601"
        }
    ],
    "documents": [
        {
            "filename": "document.pdf",
            "timestamp": "ISO-8601",
            "size": 1024000
        }
    ]
}
```

### Chat Message
```python
{
    "type": "question|answer|system|error",
    "content": "text content",
    "timestamp": "ISO-8601 timestamp",
    "sources": [  # optional, for answers
        {
            "filename": "document.pdf",
            "text": "relevant excerpt",
            "score": 0.95
        }
    ]
}
```

### Service Status Response
```python
{
    "services": {
        "rag": {
            "status": "healthy|offline",
            "url": "http://..."
        },
        "embedding": {...},
        "ingestion": {...},
        "llm": {...},
        "qdrant": {...}
    },
    "timestamp": "ISO-8601"
}
```

## Component Responsibilities

### Frontend (Browser)
- **Rendering UI** - Display chat, documents, sessions
- **State Management** - Track current session, messages
- **User Input** - Handle questions and file uploads
- **Theme Management** - Dark/light mode toggle
- **API Communication** - Fetch and POST to backend

### UI Service (Backend)
- **Routing** - Route requests to appropriate services
- **Session Management** - Create, store, retrieve sessions
- **Validation** - Validate inputs (file size, question format)
- **Error Handling** - Catch and respond to errors
- **Service Health** - Monitor backend service availability
- **File Upload** - Handle file reception and forwarding

### RAG Service (Backend)
- **Embedding** - Convert questions to vectors
- **Search** - Find relevant documents
- **Re-ranking** - Order results by relevance
- **Generation** - Create answers using LLM

### Ingestion Service (Backend)
- **Extraction** - Extract text from files
- **Chunking** - Split text into manageable pieces
- **Embedding** - Convert chunks to vectors
- **Storage** - Store in vector database

### Database Layer
- **Vector Storage** - Qdrant for embeddings
- **Metadata** - Document info and chunks
- **Caching** - Redis for fast access

## Security Considerations

### Input Validation
- File size limits (50MB max)
- File type validation
- Question length validation
- XSS prevention with HTML escaping

### Data Handling
- Session isolation
- No persistent file storage
- Temporary files cleaned up
- User data not logged

### Network
- CORS enabled for cross-origin requests
- Timeout on backend requests
- Error messages don't expose internals

## Performance Optimizations

### Frontend
- Vanilla JavaScript (no heavy frameworks)
- Event delegation for efficiency
- Lazy loading of components
- CSS animations for smooth UX

### Backend
- Async request handling
- Connection pooling
- In-memory session cache
- Efficient error handling

### Database
- Vector indexing (HNSW)
- Payload filtering
- Semantic caching
- Batch operations

## Scaling Considerations

### Current Architecture
- Single instance UI service
- In-memory session storage
- Up to ~1000 concurrent sessions

### For Higher Scale
- Multiple UI service replicas
- Distributed session store (Redis)
- Load balancer frontend
- Service mesh for communication

### Memory Usage
- ~100KB per session
- ~10MB per 1000 concurrent sessions
- Configurable session timeout

## Monitoring & Debugging

### Health Endpoints
- `/health` - Overall service health
- `/api/services-status` - Individual service status

### Logging
- Structured logging in backend
- Browser console logging on frontend
- Timestamps on all messages

### Metrics
- Request latency
- Error rates
- Session count
- Document count

## Future Enhancements

### Planned Features
- Streaming responses
- Real-time collaborative sessions
- Advanced search filters
- Document versioning
- User authentication
- Rate limiting
- Conversation export

### Technical Improvements
- WebSocket for real-time updates
- Service worker for offline support
- Progressive web app features
- Advanced caching strategies
- GraphQL API option
