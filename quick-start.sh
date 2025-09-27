#!/bin/bash

# Quick Start Script for AI Video Subtitle Generator Web App
# This script sets up everything needed to run the web application

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${PURPLE}[STEP]${NC} $1"
}

# Header
echo -e "${CYAN}"
cat << "EOF"
╔══════════════════════════════════════════════════════╗
║          AI VIDEO SUBTITLE GENERATOR                 ║
║               Web Application Setup                  ║
╚══════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Check prerequisites
log_step "Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker is not installed. Please install Docker first."
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check Docker Compose
if ! command -v docker-compose &> /dev/null; then
    log_error "Docker Compose is not installed. Please install Docker Compose first."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check if Docker is running
if ! docker info &> /dev/null; then
    log_error "Docker is not running. Please start Docker first."
    exit 1
fi

log_success "All prerequisites met"

# Create directory structure
log_step "Creating directory structure..."

directories=(
    "uploads/videos"
    "uploads/audio"  
    "output/srt"
    "output/translations"
    "cache"
    "temp"
    "logs"
    "static/css"
    "static/js"
    "static/images"
    "templates"
    "nginx/sites-available"
    "scripts"
    "monitoring"
    "ssl"
)

for dir in "${directories[@]}"; do
    mkdir -p "$dir"
done

log_success "Directory structure created"

# Create .env file if it doesn't exist
log_step "Setting up environment configuration..."

if [ ! -f .env ]; then
    cat > .env << EOF
# API Configuration
GEMINI_API_KEY=your_gemini_api_key_here

# Application Settings
SECRET_KEY=$(openssl rand -hex 32)
FLASK_ENV=production
DEBUG=false
PORT=5050

# Whisper Configuration
WHISPER_MODEL_SIZE=base

# Default Languages
DEFAULT_LANGUAGES=vietnamese,chinese,korean,french,spanish,japanese

# File Limits
MAX_FILE_SIZE=500MB
CACHE_EXPIRE_HOURS=24

# Database Settings (optional)
POSTGRES_DB=subtitle_db
POSTGRES_USER=subtitle_user
POSTGRES_PASSWORD=$(openssl rand -base64 32)

# Monitoring (optional)
GRAFANA_PASSWORD=admin

# Performance Settings
WORKERS=4
WORKER_CONCURRENCY=2

# Feature Flags
ENABLE_MONITORING=false
ENABLE_DATABASE=false
ENABLE_WORKER=false
EOF

    log_success "Created .env file with default settings"
    log_warning "Please edit .env file and add your GEMINI_API_KEY"
else
    log_info ".env file already exists"
fi

# Create Docker files
log_step "Setting up Docker configuration..."

# Create gunicorn config
cat > gunicorn.conf.py << 'EOF'
import multiprocessing
import os

# Server socket
bind = "0.0.0.0:5050"
backlog = 2048

# Worker processes
workers = int(os.environ.get('WORKERS', multiprocessing.cpu_count() * 2))
worker_class = 'gevent'
worker_connections = 1000
timeout = 300
keepalive = 2

# Restart workers
max_requests = 1000
max_requests_jitter = 100

# Logging
errorlog = '-'
loglevel = 'info'
accesslog = '-'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'subtitle-webapp'

# Server mechanics
daemon = False
pidfile = '/tmp/gunicorn.pid'
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
keyfile = None
certfile = None
EOF

# Create logging configuration
cat > logging.conf << 'EOF'
[loggers]
keys=root,gunicorn.error,gunicorn.access

[handlers]
keys=console,error_file,access_file

[formatters]
keys=generic,access

[logger_root]
level=INFO
handlers=console

[logger_gunicorn.error]
level=INFO
handlers=error_file
propagate=1
qualname=gunicorn.error

[logger_gunicorn.access]
level=INFO
handlers=access_file
propagate=0
qualname=gunicorn.access

[handler_console]
class=StreamHandler
formatter=generic
args=(sys.stdout, )

[handler_error_file]
class=FileHandler
formatter=generic
args=('/app/logs/error.log', 'a')

[handler_access_file]
class=FileHandler
formatter=access
args=('/app/logs/access.log', 'a')

[formatter_generic]
format=%(asctime)s [%(process)d] [%(levelname)s] %(message)s
datefmt=%Y-%m-%d %H:%M:%S
class=logging.Formatter

[formatter_access]
format=%(message)s
class=logging.Formatter
EOF

log_success "Docker configuration files created"

# Create basic HTML files
log_step "Creating basic HTML templates and static files..."

# Create static CSS
cat > static/css/custom.css << 'EOF'
/* Custom styles for AI Subtitle Generator */
.gradient-bg {
    background: linear-gradient(-45deg, #667eea, #764ba2, #f093fb, #f5576c);
    background-size: 400% 400%;
    animation: gradient-animation 15s ease infinite;
}

@keyframes gradient-animation {
    0%, 100% {
        background-position: 0% 50%;
    }
    50% {
        background-position: 100% 50%;
    }
}

.glass-effect {
    backdrop-filter: blur(20px);
    background: rgba(255, 255, 255, 0.1);
    border: 1px solid rgba(255, 255, 255, 0.2);
}

.neon-glow {
    box-shadow: 0 0 5px #6366f1, 0 0 20px #6366f1, 0 0 35px #6366f1;
}
EOF

# Create 404 page
cat > static/404.html << 'EOF'
<!DOCTYPE html>
<html>
<head>
    <title>Page Not Found</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
        .error { color: #e74c3c; font-size: 48px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="error">404</div>
    <h1>Page Not Found</h1>
    <p>The page you are looking for doesn't exist.</p>
    <a href="/">Go back to home</a>
</body>
</html>
EOF

log_success "Static files created"

# Create docker-compose profiles helper
cat > run-profiles.sh << 'EOF'
#!/bin/bash

# Helper script to run different Docker Compose profiles

case "$1" in
    "basic"|"")
        echo "Starting basic web application..."
        docker-compose -f docker-compose-webapp.yml up -d
        ;;
    "full")
        echo "Starting full stack with all services..."
        docker-compose -f docker-compose-webapp.yml --profile proxy --profile management --profile database up -d
        ;;
    "monitoring")
        echo "Starting with monitoring enabled..."
        docker-compose -f docker-compose-webapp.yml --profile proxy --profile monitoring up -d
        ;;
    "dev")
        echo "Starting development environment..."
        FLASK_ENV=development DEBUG=true docker-compose -f docker-compose-webapp.yml up -d
        ;;
    "stop")
        echo "Stopping all services..."
        docker-compose -f docker-compose-webapp.yml down
        ;;
    "logs")
        echo "Showing logs..."
        docker-compose -f docker-compose-webapp.yml logs -f
        ;;
    "clean")
        echo "Cleaning up containers and volumes..."
        docker-compose -f docker-compose-webapp.yml down -v
        docker system prune -f
        ;;
    *)
        echo "Usage: $0 {basic|full|monitoring|dev|stop|logs|clean}"
        echo ""
        echo "Profiles:"
        echo "  basic      - Just the web application and Redis"
        echo "  full       - Web app + Nginx + File manager + Database"
        echo "  monitoring - Web app + Nginx + Prometheus + Grafana"
        echo "  dev        - Development mode with hot reload"
        echo "  stop       - Stop all services"
        echo "  logs       - Show application logs"
        echo "  clean      - Remove containers and volumes"
        exit 1
        ;;
esac
EOF

chmod +x run-profiles.sh

# Create process script
cat > process-video.sh << 'EOF'
#!/bin/bash

# Quick video processing script

if [ $# -eq 0 ]; then
    echo "Usage: $0 <video_file_or_url> [languages]"
    echo "Example: $0 video.mp4 vietnamese,chinese,korean"
    echo "Example: $0 https://youtube.com/watch?v=abc123"
    exit 1
fi

VIDEO=$1
LANGUAGES=${2:-"vietnamese,chinese,korean,french"}

echo "Processing: $VIDEO"
echo "Languages: $LANGUAGES"

# Copy to uploads if it's a local file
if [ -f "$VIDEO" ]; then
    echo "Copying file to uploads directory..."
    cp "$VIDEO" uploads/videos/
    VIDEO="uploads/videos/$(basename "$VIDEO")"
fi

# Call the web app API or use direct processing
curl -X POST http://localhost:5050/upload \
    -F "video_url=$VIDEO" \
    -F "languages=$LANGUAGES"

echo "Processing started. Check the web interface at http://localhost:5050"
EOF

chmod +x process-video.sh

log_success "Helper scripts created"

# Build and start the application
log_step "Building and starting the application..."

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check if GEMINI_API_KEY is set
if [ "$GEMINI_API_KEY" = "your_gemini_api_key_here" ]; then
    log_warning "GEMINI_API_KEY is not configured. AI translation will be limited."
    read -p "Do you want to enter your Gemini API key now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Enter your Gemini API key: " api_key
        sed -i "s/your_gemini_api_key_here/$api_key/" .env
        log_success "API key updated"
    fi
fi

# Build the application
log_info "Building Docker images..."
docker-compose -f docker-compose-webapp.yml build

# Start basic services
log_info "Starting services..."
docker-compose -f docker-compose-webapp.yml up -d

# Wait for services to be ready
log_info "Waiting for services to be ready..."
sleep 10

# Check if services are running
if docker-compose -f docker-compose-webapp.yml ps | grep -q "Up"; then
    log_success "Services started successfully!"
else
    log_error "Some services failed to start. Check logs with: docker-compose -f docker-compose-webapp.yml logs"
fi

# Show status
log_step "Service Status"
docker-compose -f docker-compose-webapp.yml ps

# Final instructions
echo ""
log_success "Setup completed successfully!"
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗"
echo -e "║                   QUICK ACCESS                       ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "🌐 Web Application: http://localhost:5050"
echo "📁 File Manager: http://localhost:8080 (if enabled)"
echo "📊 Monitoring: http://localhost:3000 (if enabled)"
echo ""
echo -e "${YELLOW}Common Commands:${NC}"
echo "  View logs:           docker-compose -f docker-compose-webapp.yml logs -f"
echo "  Stop services:       ./run-profiles.sh stop"
echo "  Process video:       ./process-video.sh video.mp4"
echo "  Full stack:          ./run-profiles.sh full"
echo ""
echo -e "${GREEN}🎉 Ready to generate subtitles!${NC}"
echo ""

# Open browser if available
if command -v xdg-open > /dev/null; then
    xdg-open http://localhost:5050
elif command -v open > /dev/null; then
    open http://localhost:5050
fi