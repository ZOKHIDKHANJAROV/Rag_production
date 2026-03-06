# RAG UI Service - Deployment Guide

## 🚀 Deployment Options

### Option 1: Local Development (Recommended for Testing)

```bash
# 1. Navigate to service directory
cd d:\rag-production\ui-service

# 2. Create virtual environment
python -m venv venv

# 3. Activate environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Copy and configure environment file
copy .env.example .env
# Edit .env if needed (optional)

# 6. Run the application
uvicorn app.main:app --reload

# 7. Access the system
# Open browser: http://localhost:8000
```

### Option 2: Docker Container (Recommended for Production)

```bash
# 1. Build the image
docker build -t rag-ui-service:latest .

# 2. Run the container
docker run -d \
  --name rag-ui \
  -p 8000:8000 \
  --env RAG_SERVICE_URL=http://rag-service:8003/ask \
  --env INGESTION_SERVICE_URL=http://ingestion-service:8004/upload \
  --env EMBEDDING_SERVICE_URL=http://embedding-service:8001 \
  rag-ui-service:latest

# 3. Access the system
# Open browser: http://localhost:8000

# 4. Check logs
docker logs -f rag-ui

# 5. Stop the container
docker stop rag-ui
docker rm rag-ui
```

### Option 3: Docker Compose (Full Stack)

```bash
# 1. From project root directory
cd d:\rag-production

# 2. Start only UI service (with other services running)
docker-compose up ui-service

# 3. Or start entire stack
docker-compose up

# 4. Access the system
# Open browser: http://localhost:8000

# 5. View logs
docker-compose logs -f ui-service

# 6. Stop the service
docker-compose down
```

## 📋 Prerequisites

### For Local Development
- Python 3.11 or higher
- pip (Python package manager)
- Virtual environment support
- Internet connection

### For Docker
- Docker installed and running
- Docker Compose (optional, for full stack)
- Internet connection for pulling images

### For Production
- All of the above, plus:
- Stable network connection
- Sufficient disk space (at least 1GB)
- Backend services running (RAG, Embedding, Ingestion)

## 🔧 Configuration

### Environment Variables

Create or edit `.env` file:

```bash
# Logging
LOG_LEVEL=INFO                              # DEBUG, INFO, WARNING, ERROR

# File Upload Settings
MAX_FILE_SIZE=50                           # Maximum file size in MB

# Backend Service URLs
RAG_SERVICE_URL=http://rag-service:8003/ask
INGESTION_SERVICE_URL=http://ingestion-service:8004/upload
EMBEDDING_SERVICE_URL=http://embedding-service:8001
LLM_SERVICE_URL=http://llm-service:8002
QDRANT_URL=http://qdrant:6333

# API Settings
REQUEST_TIMEOUT=300                        # Timeout in seconds

# Server Settings
UVICORN_HOST=0.0.0.0                      # Host address
UVICORN_PORT=8000                         # Port number
```

### Docker Environment Variables

Pass via command line:
```bash
docker run -d \
  -e LOG_LEVEL=INFO \
  -e MAX_FILE_SIZE=50 \
  -e RAG_SERVICE_URL=http://rag-service:8003/ask \
  # ... other variables
  rag-ui-service:latest
```

Or in docker-compose.yml:
```yaml
ui-service:
  environment:
    LOG_LEVEL: INFO
    MAX_FILE_SIZE: 50
    RAG_SERVICE_URL: http://rag-service:8003/ask
```

## 📝 Requirements

### Python Dependencies

All defined in `requirements.txt`:

```
fastapi==0.104.1        # Web framework
uvicorn[standard]==0.24.0  # ASGI server
jinja2==3.1.2           # Template engine
requests==2.31.0        # HTTP client
python-multipart==0.0.6 # Form data parsing
pydantic==2.5.0         # Data validation
python-dotenv==1.0.0    # Environment variables
```

### System Requirements

- **CPU**: 1 core minimum (2+ recommended)
- **RAM**: 512MB minimum (1GB+ recommended)
- **Disk**: 100MB for application + uploads
- **Network**: Stable connection to backend services

## ✅ Verification

### Check Service is Running

```bash
# 1. Test health endpoint
curl http://localhost:8000/health

# 2. Test services status
curl http://localhost:8000/api/services-status

# 3. Create test session
curl -X POST http://localhost:8000/api/session/new

# 4. Check in browser
# Visit http://localhost:8000
# Should load the UI successfully
```

### Verify Backend Services

The UI will show service status. Check for:
- ✅ RAG Service: Green then it's healthy
- ✅ Embedding Service: Green indicator
- ✅ Ingestion Service: Green indicator
- ✅ LLM Service: Green indicator
- ✅ Qdrant: Green indicator

If any are red (offline):
1. Check if backend services are running
2. Verify network connectivity
3. Check service URLs in environment variables

## 🔐 Security Considerations

### Before Production

1. **Change Default Settings**
   - Set appropriate LOG_LEVEL (INFO, not DEBUG)
   - Adjust REQUEST_TIMEOUT as needed
   - Set MAX_FILE_SIZE appropriately

2. **Network Security**
   - Use HTTPS in production (reverse proxy)
   - Restrict access via firewall
   - Use VPN for sensitive networks

3. **File Handling**
   - Implement scanning for malicious files
   - Set resource limits
   - Monitor disk usage

4. **Authentication**
   - Consider adding user authentication
   - Implement rate limiting
   - Add request validation

## 📊 Monitoring

### Log Files

```bash
# Local development
# Check console output during run

# Docker
docker logs -f rag-ui

# Docker Compose
docker-compose logs -f ui-service
```

### Health Checks

```bash
# Health endpoint
curl http://localhost:8000/health

# Services status
curl http://localhost:8000/api/services-status

# Automatic monitoring (every 60s in browser)
# Service status refreshed automatically
```

### Performance Metrics

Monitor:
- Request response time
- Session count
- Memory usage
- CPU usage
- Disk space for uploads

## 🔧 Troubleshooting

### Service Won't Start

```bash
# Error: Port 8000 already in use
# Solution: Kill process on port 8000
# Windows:
netstat -ano | findstr :8000
taskkill /PID <PID> /F

# Linux/macOS:
lsof -ti:8000 | xargs kill -9
```

### Dependencies Installation Fails

```bash
# Update pip first
pip install --upgrade pip

# Clear pip cache
pip cache purge

# Reinstall requirements
pip install -r requirements.txt
```

### Backend Services Not Accessible

```bash
# Check if services are running
docker ps

# Start services if needed
docker-compose up rag-service embedding-service ingestion-service

# Verify connectivity
curl http://rag-service:8003/health
curl http://embedding-service:8001/health
```

### File Upload Issues

```bash
# Check file size limit
# Edit MAX_FILE_SIZE in .env

# Check disk space
df -h  # Linux/macOS
dir   # Windows

# Check file permissions
# Ensure write access to upload directory
```

## 📈 Scaling Considerations

### Single Instance
- Suitable for development and testing
- Up to ~100 concurrent users
- In-memory session storage

### Multiple Instances
- Use load balancer (nginx, HAProxy)
- Shared session store (Redis)
- Distributed file storage

### Configuration for Scale

```yaml
version: '3.9'
services:
  ui-service-1:
    build: ./ui-service
    environment:
      REDIS_URL: redis://redis:6379
    depends_on:
      - redis

  ui-service-2:
    build: ./ui-service
    environment:
      REDIS_URL: redis://redis:6379
    depends_on:
      - redis

  nginx:
    image: nginx:latest
    ports:
      - 8000:8000
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
```

## 📚 Additional Resources

### Documentation Files
- [README.md](README.md) - Complete documentation
- [QUICKSTART.md](QUICKSTART.md) - 5-minute setup
- [ARCHITECTURE.md](ARCHITECTURE.md) - System design
- [NAVIGATION.md](NAVIGATION.md) - Navigation guide

### API Examples
- [api-examples.sh](api-examples.sh) - Bash examples
- [api-examples.ps1](api-examples.ps1) - PowerShell examples

### Configuration
- [.env.example](.env.example) - Environment template
- [Dockerfile](Dockerfile) - Container configuration
- [docker-compose.yml](../docker-compose.yml) - Full stack config

## 🆘 Support

### Getting Help

1. Check [QUICKSTART.md](QUICKSTART.md) for common issues
2. Review [README.md](README.md) for detailed documentation
3. Check logs: `docker logs -f rag-ui` or console output
4. Test endpoints with api-examples scripts
5. Verify backend services are running

### Reporting Issues

Include:
- Error message or screenshot
- Steps to reproduce
- Environment information
- Log output
- Backend service status

## 📝 Summary

| Aspect | Details |
|--------|---------|
| **Default Port** | 8000 |
| **Memory Usage** | ~50-100MB |
| **Startup Time** | 2-3 seconds |
| **Health Check** | /health endpoint |
| **Max Sessions** | ~1000 (in-memory) |
| **Session Timeout** | Until restart (persistent) |
| **File Upload Limit** | 50MB (configurable) |
| **Request Timeout** | 300s (configurable) |

## ✨ Next Steps

1. **Deploy** - Choose deployment option above
2. **Configure** - Set environment variables
3. **Verify** - Test health endpoints
4. **Monitor** - Check logs and status
5. **Use** - Access at http://localhost:8000

---

**Ready to deploy?** Follow the option that suits your environment and enjoy the RAG UI Service! 🚀
