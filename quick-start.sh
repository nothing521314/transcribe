#!/bin/bash

# Fixed Quick Start Script for AI Video Subtitle Generator
# Addresses permission issues and missing dependencies

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
║            Fixed Setup Script v2.0                   ║
╚══════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Check and install prerequisites
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

# Create and fix directory structure
log_step "Creating and fixing directory structure..."

directories=(
    "uploads/videos" "uploads/audio" "output/srt" "output/translations"
    "cache" "temp" "logs" "static/css" "static/js" "static/images"
    "templates" "nginx/sites-available" "scripts" "monitoring" "ssl"
)

for dir in "${directories[@]}"; do
    mkdir -p "$dir"
    chmod 755 "$dir" 2>/dev/null || true
done

# Fix permissions
if [ "$(id -u)" -eq 0 ]; then
    chown -R 1000:1000 uploads output cache temp logs
    log_success "Fixed directory ownership"
else
    log_warning "Not running as root - some permission fixes may be limited"
fi

log_success "Directory structure created and fixed"

# Create essential configuration files
log_step "Creating essential configuration files..."

# 1. Fixed .env file
cat > .env << EOF
# API Configuration
GEMINI_API_KEY=AIzaSyBjRL9arU5wzSldPN91tZvXflftasrNPZA

# Application Settings
SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || echo "default-secret-key-$(date +%s)")
FLASK_ENV=development
DEBUG=true
PORT=5050

# Whisper Configuration
WHISPER_MODEL_SIZE=base

# Default Languages
DEFAULT_LANGUAGES=vietnamese,chinese,korean,french

# File Limits
MAX_FILE_SIZE=500MB
CACHE_EXPIRE_HOURS=24

# Performance
WORKERS=2
TIMEOUT=300

# Development flags
USE_DEV_SERVER=true
SKIP_MODEL_PRELOAD=false
EOF

# 2. Gunicorn configuration
cat > gunicorn.conf.py << 'EOF'
import os
import multiprocessing

# Server socket
bind = "0.0.0.0:5050"
backlog = 2048

# Worker processes
workers = int(os.environ.get('WORKERS', 2))
worker_class = 'gevent'
worker_connections = 1000
timeout = int(os.environ.get('TIMEOUT', 300))
keepalive = 2

# Restart workers
max_requests = 1000
max_requests_jitter = 100

# Logging
errorlog = '-'
loglevel = 'info'
accesslog = '-'

# Process naming
proc_name = 'subtitle-webapp'

# Server mechanics
daemon = False
preload_app = True
EOF

# 3. Simple logging config
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
args=(sys.stdout, )

[formatter_generic]
format=%(asctime)s [%(levelname)s] %(message)s
class=logging.Formatter
EOF

# 4. Fixed startup script
mkdir -p scripts
cat > scripts/start-webapp.sh << 'EOF'
#!/bin/bash
set -e

echo "🚀 Starting AI Video Subtitle Generator..."

# Environment
export FLASK_ENV=${FLASK_ENV:-development}
export DEBUG=${DEBUG:-true}
export PORT=${PORT:-5050}

# Create and fix directories
mkdir -p uploads output cache temp logs /home/appuser/.cache/whisper
chmod -R 755 uploads output cache temp logs 2>/dev/null || true

echo "📁 Directories setup completed"

# Check Python packages
echo "🔍 Checking Python environment..."
python -c "
import sys
required = ['flask', 'whisper', 'pysrt']
missing = []
for pkg in required:
    try:
        __import__(pkg)
        print(f'✓ {pkg}')
    except ImportError:
        missing.append(pkg)
        print(f'✗ {pkg} missing')

if missing:
    print(f'Installing missing packages: {missing}')
    import subprocess
    subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + missing)
"

# Pre-load Whisper model (optional)
if [ "$SKIP_MODEL_PRELOAD" != "true" ]; then
    echo "📦 Pre-loading Whisper model..."
    python -c "
import whisper
import os
try:
    model_size = os.environ.get('WHISPER_MODEL_SIZE', 'base')
    model = whisper.load_model(model_size)
    print(f'✓ Whisper {model_size} model loaded')
except Exception as e:
    print(f'⚠ Model preload failed: {e}')
" || echo "Model will be loaded on first use"
fi

# Start application
echo "🌐 Starting web application..."
if [ "$DEBUG" = "true" ] || [ "$FLASK_ENV" = "development" ]; then
    echo "Development mode"
    exec python web_app.py
else
    echo "Production mode with Gunicorn"
    exec gunicorn --config gunicorn.conf.py web_app:app
fi
EOF

chmod +x scripts/start-webapp.sh

# 5. Fixed Dockerfile for webapp
cat > Dockerfile.webapp << 'EOF'
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    bc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create user with proper home directory
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /home/appuser -s /bin/bash appuser && \
    mkdir -p /home/appuser/.cache/whisper && \
    chown -R appuser:appuser /home/appuser

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements-webapp.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-webapp.txt

# Create app directories
RUN mkdir -p uploads output cache temp logs static templates && \
    chown -R appuser:appuser /app

# Copy application files
COPY web_app.py video_subtitle_processor.py enhanced_translation_manager.py ./
COPY templates/ templates/
COPY static/ static/
COPY gunicorn.conf.py logging.conf ./
COPY scripts/start-webapp.sh ./

# Make script executable and fix ownership
RUN chmod +x start-webapp.sh && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 5050

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5050/api/stats || exit 1

# Start application
CMD ["./start-webapp.sh"]
EOF

# 6. Simplified docker-compose
cat > docker-compose-simple.yml << 'EOF'
services:
  subtitle-webapp:
    build:
      context: .
      dockerfile: Dockerfile.webapp
    container_name: subtitle-webapp
    ports:
      - "5050:5050"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
      - WHISPER_MODEL_SIZE=${WHISPER_MODEL_SIZE:-base}
      - SECRET_KEY=${SECRET_KEY}
      - FLASK_ENV=${FLASK_ENV:-development}
      - DEBUG=${DEBUG:-true}
      - SKIP_MODEL_PRELOAD=${SKIP_MODEL_PRELOAD:-false}
    volumes:
      - ./uploads:/app/uploads
      - ./output:/app/output
      - ./cache:/app/cache
      - ./temp:/app/temp
      - ./logs:/app/logs
      - whisper-models:/home/appuser/.cache/whisper
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 6G
          cpus: '3.0'

  redis:
    image: redis:7-alpine
    container_name: subtitle-redis
    ports:
      - "6379:6379"
    restart: unless-stopped
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru

volumes:
  whisper-models:
EOF

# 7. Helper scripts
cat > run-simple.sh << 'EOF'
#!/bin/bash

case "$1" in
    "start"|"")
        echo "🚀 Starting AI Subtitle Generator..."
        docker-compose -f docker-compose-simple.yml up -d
        echo "✅ Started! Access at http://localhost:5050"
        ;;
    "stop")
        docker-compose -f docker-compose-simple.yml down
        ;;
    "logs")
        docker-compose -f docker-compose-simple.yml logs -f
        ;;
    "rebuild")
        docker-compose -f docker-compose-simple.yml down
        docker-compose -f docker-compose-simple.yml build --no-cache
        docker-compose -f docker-compose-simple.yml up -d
        ;;
    "clean")
        docker-compose -f docker-compose-simple.yml down -v
        docker system prune -f
        ;;
    *)
        echo "Usage: $0 {start|stop|logs|rebuild|clean}"
        ;;
esac
EOF

chmod +x run-simple.sh

cat > process-video-simple.sh << 'EOF'
#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <video_file_or_url> [languages]"
    echo "Example: $0 video.mp4 vietnamese,chinese,korean"
    exit 1
fi

VIDEO=$1
LANGUAGES=${2:-"vietnamese,chinese,korean"}

echo "📹 Processing: $VIDEO"
echo "🌐 Languages: $LANGUAGES"

# Copy to uploads if local file
if [ -f "$VIDEO" ]; then
    cp "$VIDEO" uploads/videos/
    echo "📁 File copied to uploads/"
fi

echo "🚀 Processing started. Check web interface at http://localhost:5050"
echo "📊 Or check logs: ./run-simple.sh logs"
EOF

chmod +x process-video-simple.sh

log_success "Configuration files created"

# Create basic HTML templates
log_step "Creating basic templates..."

mkdir -p templates
cat > templates/base.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Subtitle Generator</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen">
    <nav class="bg-blue-600 text-white p-4">
        <div class="container mx-auto">
            <h1 class="text-2xl font-bold">🎬 AI Subtitle Generator</h1>
        </div>
    </nav>
    
    <main class="container mx-auto px-4 py-8">
        {% block content %}{% endblock %}
    </main>
</body>
</html>
EOF

log_success "Basic templates created"

# Build and start
log_step "Building and starting services..."

# Load environment
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs) 2>/dev/null || true
fi

# Check API key
if [ "$GEMINI_API_KEY" = "your_gemini_api_key_here" ]; then
    log_warning "⚠️  GEMINI_API_KEY not configured"
    read -p "Enter your Gemini API key (or press Enter to skip): " api_key
    if [ ! -z "$api_key" ]; then
        sed -i "s/your_gemini_api_key_here/$api_key/" .env
        export GEMINI_API_KEY=$api_key
        log_success "API key configured"
    fi
fi

# Build
log_info "Building Docker image..."
docker-compose -f docker-compose-simple.yml build

# Start
log_info "Starting services..."
docker-compose -f docker-compose-simple.yml up -d

# Wait and check
log_info "Waiting for services..."
sleep 15

if docker-compose -f docker-compose-simple.yml ps | grep -q "Up"; then
    log_success "🎉 Setup completed successfully!"
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════╗"
    echo -e "║                 🎊 ALL READY! 🎊                     ║"
    echo -e "╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "🌐 Web Interface:  http://localhost:5050"
    echo "🔧 Redis:          http://localhost:6379"
    echo ""
    echo -e "${GREEN}Quick Commands:${NC}"
    echo "  📊 View logs:      ./run-simple.sh logs"
    echo "  🛑 Stop:           ./run-simple.sh stop"
    echo "  🎬 Process video:  ./process-video-simple.sh video.mp4"
    echo "  🔨 Rebuild:        ./run-simple.sh rebuild"
    echo ""
else
    log_error "❌ Some services failed to start"
    echo "Check logs: ./run-simple.sh logs"
fi

# Show status
docker-compose -f docker-compose-simple.yml ps

# Try to open browser
if command -v xdg-open &> /dev/null; then
    sleep 2 && xdg-open http://localhost:5050 &
elif command -v open &> /dev/null; then
    sleep 2 && open http://localhost:5050 &
fi