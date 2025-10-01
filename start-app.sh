#!/bin/bash

# Quick Start Script for AI Video Subtitle Generator
# Simplified version with web-app and filebrowser only

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${PURPLE}[STEP]${NC} $1"; }

# Header
echo -e "${CYAN}"
cat << "EOF"
╔══════════════════════════════════════════════════════╗
║          AI VIDEO SUBTITLE GENERATOR                 ║
║            Quick Setup Script v3.0                   ║
╚══════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Check prerequisites
log_step "Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    log_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

if ! docker info &> /dev/null; then
    log_error "Docker is not running. Please start Docker first."
    exit 1
fi

log_success "Prerequisites check passed"

# Create directory structure
log_step "Creating directory structure..."

directories=(
    "uploads" "output" "cache" "temp" "logs" 
    "static/css" "static/js" "templates"
    "scripts"
)

for dir in "${directories[@]}"; do
    mkdir -p "$dir"
    chmod 755 "$dir" 2>/dev/null || true
done

log_success "Directory structure created"

# Create .env file if not exists
log_step "Creating configuration files..."

if [ ! -f .env ]; then
    cat > .env << 'EOF'
# Application Settings
SECRET_KEY=your-secret-key-change-this
FLASK_ENV=production
DEBUG=false

# Whisper Configuration
WHISPER_MODEL_SIZE=base

# Cache expiration in hours
CACHE_EXPIRE_HOURS=168

# Performance
WORKERS=4
TIMEOUT=600

# File Browser (set to true to disable authentication)
FB_NOAUTH=false
EOF
    log_success "Created .env file"
else
    log_info ".env file already exists"
fi

# Create gunicorn config
if [ ! -f gunicorn.conf.py ]; then
    cat > gunicorn.conf.py << 'EOF'
import os
import multiprocessing

bind = "0.0.0.0:5050"
backlog = 2048

workers = int(os.environ.get('WORKERS', 4))
worker_class = 'gevent'
worker_connections = 1000
timeout = int(os.environ.get('TIMEOUT', 600))
keepalive = 2

max_requests = 1000
max_requests_jitter = 100

errorlog = '-'
loglevel = 'info'
accesslog = '-'

proc_name = 'subtitle-webapp'
daemon = False
preload_app = True
EOF
    log_success "Created gunicorn.conf.py"
fi

# Create logging config
if [ ! -f logging.conf ]; then
    cat > logging.conf << 'EOF'
[loggers]
keys=root

[handlers]
keys=console

[formatters]
keys=generic

[logger_root]
level=INFO
handlers=console

[handler_console]
class=StreamHandler
formatter=generic
args=(sys.stdout,)

[formatter_generic]
format=%(asctime)s [%(levelname)s] %(message)s
class=logging.Formatter
EOF
    log_success "Created logging.conf"
fi

# Create startup script
mkdir -p scripts
cat > scripts/start-webapp.sh << 'EOF'
#!/bin/bash
set -e

echo "Starting AI Video Subtitle Generator..."

export FLASK_ENV=${FLASK_ENV:-production}
export DEBUG=${DEBUG:-false}
export PORT=${PORT:-5050}

# Create directories
mkdir -p uploads output cache temp logs /home/appuser/.cache/whisper
chmod -R 755 uploads output cache temp logs 2>/dev/null || true

echo "Directories setup completed"

# Check dependencies
echo "Checking dependencies..."
python -c "
import sys
required = ['flask', 'flask_socketio', 'eventlet']
for pkg in required:
    try:
        __import__(pkg)
        print(f'✓ {pkg}')
    except ImportError:
        print(f'✗ {pkg} missing')
        sys.exit(1)
"

# Pre-load Whisper model
if [ "$SKIP_MODEL_PRELOAD" != "true" ]; then
    echo "Pre-loading Whisper model..."
    python -c "
from faster_whisper import WhisperModel
import os
try:
    model_size = os.environ.get('WHISPER_MODEL_SIZE', 'base')
    model = WhisperModel(model_size, device='cpu', compute_type='int8')
    print(f'✓ Whisper {model_size} model loaded')
except Exception as e:
    print(f'⚠ Model preload failed: {e}')
" || echo "Model will be loaded on first use"
fi

# Start application
echo "Starting web application..."
if [ "$DEBUG" = "true" ] || [ "$FLASK_ENV" = "development" ]; then
    echo "Development mode"
    exec python web_app.py
else
    echo "Production mode with Gunicorn"
    exec gunicorn --config gunicorn.conf.py web_app:app
fi
EOF

chmod +x scripts/start-webapp.sh
log_success "Created startup script"

# Create Dockerfile if not exists
if [ ! -f Dockerfile ]; then
    cat > Dockerfile << 'EOF'
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    gcc \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && \
    useradd -r -g appuser -d /home/appuser -s /bin/bash appuser && \
    mkdir -p /home/appuser/.cache/whisper && \
    chown -R appuser:appuser /home/appuser

WORKDIR /app

COPY requirements-webapp.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-webapp.txt

RUN mkdir -p uploads output cache temp logs static templates && \
    chown -R appuser:appuser /app

COPY web_app.py video_subtitle_processor.py enhanced_translation_manager.py ./
COPY templates/ templates/
COPY static/ static/
COPY gunicorn.conf.py logging.conf ./
COPY scripts/start-webapp.sh ./

RUN chmod +x start-webapp.sh && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 5050

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5050/api/stats || exit 1

CMD ["./start-webapp.sh"]
EOF
    log_success "Created Dockerfile"
fi

# Create helper scripts
cat > run.sh << 'EOF'
#!/bin/bash

case "$1" in
    "start"|"")
        echo "Starting services..."
        docker-compose up -d
        echo "✓ Started! Access at:"
        echo "  Web App: http://localhost:5050"
        echo "  File Browser: http://localhost:8080"
        ;;
    "stop")
        docker-compose down
        ;;
    "logs")
        docker-compose logs -f subtitle-webapp
        ;;
    "restart")
        docker-compose restart
        ;;
    "rebuild")
        docker-compose down
        docker-compose build --no-cache
        docker-compose up -d
        ;;
    "clean")
        docker-compose down -v
        docker system prune -f
        ;;
    "status")
        docker-compose ps
        ;;
    *)
        echo "Usage: $0 {start|stop|logs|restart|rebuild|clean|status}"
        ;;
esac
EOF

chmod +x run.sh
log_success "Created run.sh helper script"

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs) 2>/dev/null || true
fi

# Build and start
log_step "Building Docker image..."
docker-compose build

log_step "Starting services..."
docker-compose up -d

# Wait for services
log_info "Waiting for services to start..."
sleep 10

# Check health
log_step "Checking service health..."
for i in {1..30}; do
    if curl -f -s http://localhost:5050/api/stats > /dev/null 2>&1; then
        log_success "Web application is healthy!"
        break
    fi
    if [ $i -eq 30 ]; then
        log_warning "Web application health check timeout"
        log_info "Check logs: ./run.sh logs"
    fi
    sleep 2
done

# Final status
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗"
echo -e "║                 🎉 ALL READY! 🎉                     ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Access Points:${NC}"
echo "  🌐 Web App:        http://localhost:5050"
echo "  📁 File Browser:   http://localhost:8080"
echo ""
echo -e "${GREEN}Quick Commands:${NC}"
echo "  ./run.sh logs      - View logs"
echo "  ./run.sh stop      - Stop services"
echo "  ./run.sh restart   - Restart services"
echo "  ./run.sh rebuild   - Rebuild from scratch"
echo "  ./run.sh status    - Check status"
echo ""

# Show status
docker-compose ps

# Try to open browser
if command -v xdg-open &> /dev/null; then
    sleep 2 && xdg-open http://localhost:5050 &
elif command -v open &> /dev/null; then
    sleep 2 && open http://localhost:5050 &
fi