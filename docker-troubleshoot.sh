#!/bin/bash

# Docker Troubleshooting Script for AI Subtitle Generator

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

echo -e "${BLUE}Docker Troubleshooting for AI Subtitle Generator${NC}"
echo "=================================================="

# Function to fix permissions
fix_permissions() {
    log_info "Fixing permissions..."
    
    # Create directories if they don't exist
    mkdir -p uploads output cache temp logs static
    
    # Fix ownership (run as root/sudo if needed)
    if [ "$(id -u)" -eq 0 ]; then
        chown -R 1000:1000 uploads output cache temp logs
        chmod -R 755 uploads output cache temp logs
        log_success "Fixed directory permissions"
    else
        log_warning "Run with sudo to fix permissions: sudo ./docker-troubleshoot.sh fix-permissions"
        # Try to fix what we can
        chmod -R 755 uploads output cache temp logs 2>/dev/null || log_warning "Could not fix some permissions"
    fi
}

# Function to clean up Docker
cleanup_docker() {
    log_info "Cleaning up Docker resources..."
    
    # Stop all containers
    docker-compose -f docker-compose-webapp.yml down 2>/dev/null || true
    
    # Remove dangling images
    docker image prune -f
    
    # Remove unused volumes
    docker volume prune -f
    
    # Remove unused networks
    docker network prune -f
    
    log_success "Docker cleanup completed"
}

# Function to rebuild with no cache
rebuild_fresh() {
    log_info "Rebuilding containers from scratch..."
    
    # Stop everything
    docker-compose -f docker-compose-webapp.yml down -v
    
    # Remove images
    docker-compose -f docker-compose-webapp.yml down --rmi all
    
    # Build with no cache
    docker-compose -f docker-compose-webapp.yml build --no-cache
    
    log_success "Fresh rebuild completed"
}

# Function to check container logs
check_logs() {
    log_info "Showing container logs..."
    echo "=========================="
    
    # Show logs from all services
    docker-compose -f docker-compose-webapp.yml logs --tail=50
}

# Function to test container interactively
test_container() {
    log_info "Starting container in interactive mode for testing..."
    
    docker run -it --rm \
        -v $(pwd)/uploads:/app/uploads \
        -v $(pwd)/output:/app/output \
        -v $(pwd)/cache:/app/cache \
        -e DEBUG=true \
        -e FLASK_ENV=development \
        --name subtitle-test \
        subtitle-webapp_subtitle-webapp:latest \
        /bin/bash
}

# Function to create a minimal working Dockerfile for testing
create_minimal_dockerfile() {
    log_info "Creating minimal Dockerfile for testing..."
    
    cat > Dockerfile.minimal << 'EOF'
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    bc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask \
    gunicorn \
    openai-whisper \
    pysrt \
    requests \
    python-dotenv \
    tqdm \
    numpy

# Create user and directories
RUN useradd -r -s /bin/bash appuser && \
    mkdir -p /app /home/appuser/.cache/whisper && \
    chown -R appuser:appuser /app /home/appuser

WORKDIR /app
USER appuser

# Simple test app
RUN echo 'from flask import Flask; app = Flask(__name__); @app.route("/")
def hello(): return "Hello World!"; @app.route("/api/stats")
def stats(): return {"status": "ok"}; 
if __name__ == "__main__": app.run(host="0.0.0.0", port=5050)' > test_app.py

EXPOSE 5050
CMD ["python", "test_app.py"]
EOF

    log_success "Created Dockerfile.minimal"
    log_info "Build with: docker build -f Dockerfile.minimal -t subtitle-test ."
    log_info "Run with: docker run -p 5050:5050 subtitle-test"
}

# Function to check system requirements
check_requirements() {
    log_info "Checking system requirements..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
    else
        log_success "Docker: $(docker --version)"
    fi
    
    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed"
    else
        log_success "Docker Compose: $(docker-compose --version)"
    fi
    
    # Check available disk space
    AVAILABLE_SPACE=$(df . | awk 'NR==2 {print $4}')
    AVAILABLE_GB=$((AVAILABLE_SPACE/1024/1024))
    if [ "$AVAILABLE_GB" -lt 5 ]; then
        log_warning "Low disk space: ${AVAILABLE_GB}GB available (recommend 5GB+)"
    else
        log_success "Disk space: ${AVAILABLE_GB}GB available"
    fi
    
    # Check available memory
    if command -v free &> /dev/null; then
        AVAILABLE_MEM=$(free -g | awk 'NR==2{printf "%d", $7}')
        if [ "$AVAILABLE_MEM" -lt 4 ]; then
            log_warning "Low memory: ${AVAILABLE_MEM}GB available (recommend 4GB+)"
        else
            log_success "Memory: ${AVAILABLE_MEM}GB available"
        fi
    fi
}

# Function to create a development environment
setup_development() {
    log_info "Setting up development environment..."
    
    # Create development docker-compose
    cat > docker-compose-dev.yml << 'EOF'
services:
  subtitle-webapp-dev:
    build:
      context: .
      dockerfile: Dockerfile.minimal
    ports:
      - "5050:5050"
    environment:
      - FLASK_ENV=development
      - DEBUG=true
    volumes:
      - ./uploads:/app/uploads
      - ./output:/app/output
      - ./web_app.py:/app/web_app.py:ro
      - ./video_subtitle_processor.py:/app/video_subtitle_processor.py:ro
    restart: unless-stopped
    command: python test_app.py

  redis-dev:
    image: redis:7-alpine
    ports:
      - "6379:6379"
EOF

    log_success "Created docker-compose-dev.yml"
    log_info "Start with: docker-compose -f docker-compose-dev.yml up"
}

# Function to fix common issues
fix_common_issues() {
    log_info "Fixing common issues..."
    
    # 1. Fix .env file
    if [ ! -f .env ]; then
        log_info "Creating .env file..."
        cat > .env << EOF
GEMINI_API_KEY=your_gemini_api_key_here
WHISPER_MODEL_SIZE=base
SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || echo "default-secret-key")
FLASK_ENV=development
DEBUG=true
EOF
    fi
    
    # 2. Fix directory permissions
    fix_permissions
    
    # 3. Create missing config files
    if [ ! -f gunicorn.conf.py ]; then
        log_info "Creating gunicorn.conf.py..."
        cat > gunicorn.conf.py << 'EOF'
bind = "0.0.0.0:5050"
workers = 2
worker_class = "gevent"
timeout = 300
keepalive = 2
max_requests = 1000
preload_app = True
EOF
    fi
    
    # 4. Create logging config
    if [ ! -f logging.conf ]; then
        log_info "Creating logging.conf..."
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
    fi
    
    # 5. Create scripts directory
    mkdir -p scripts
    if [ ! -f scripts/start-webapp.sh ]; then
        log_info "Creating simplified startup script..."
        cat > scripts/start-webapp.sh << 'EOF'
#!/bin/bash
set -e

echo "Starting AI Subtitle Generator..."

# Create directories
mkdir -p uploads output cache temp logs

# Set permissions
chmod -R 755 uploads output cache temp logs

# Start application
if [ "$DEBUG" = "true" ]; then
    echo "Starting in development mode..."
    python web_app.py
else
    echo "Starting with gunicorn..."
    exec gunicorn --config gunicorn.conf.py web_app:app
fi
EOF
        chmod +x scripts/start-webapp.sh
    fi
    
    log_success "Common issues fixed"
}

# Main menu
case "${1:-menu}" in
    "fix-permissions")
        fix_permissions
        ;;
    "cleanup")
        cleanup_docker
        ;;
    "rebuild")
        rebuild_fresh
        ;;
    "logs")
        check_logs
        ;;
    "test")
        test_container
        ;;
    "minimal")
        create_minimal_dockerfile
        ;;
    "requirements")
        check_requirements
        ;;
    "dev")
        setup_development
        ;;
    "fix")
        fix_common_issues
        ;;
    "quick-fix")
        log_info "Running quick fix sequence..."
        fix_common_issues
        cleanup_docker
        create_minimal_dockerfile
        log_success "Quick fix completed!"
        echo ""
        echo "Next steps:"
        echo "1. Build minimal image: docker build -f Dockerfile.minimal -t subtitle-test ."
        echo "2. Test it: docker run -p 5050:5050 subtitle-test"
        echo "3. If working, rebuild full app: docker-compose -f docker-compose-webapp.yml build --no-cache"
        ;;
    "menu"|*)
        echo ""
        echo "Docker Troubleshooting Options:"
        echo "==============================="
        echo ""
        echo "Basic fixes:"
        echo "  ./docker-troubleshoot.sh fix-permissions  - Fix file permissions"
        echo "  ./docker-troubleshoot.sh fix              - Fix common configuration issues"
        echo "  ./docker-troubleshoot.sh quick-fix        - Run all quick fixes"
        echo ""
        echo "Docker maintenance:"
        echo "  ./docker-troubleshoot.sh cleanup          - Clean up Docker resources"
        echo "  ./docker-troubleshoot.sh rebuild          - Rebuild containers from scratch"
        echo "  ./docker-troubleshoot.sh logs             - Show container logs"
        echo ""
        echo "Development tools:"
        echo "  ./docker-troubleshoot.sh minimal          - Create minimal test Dockerfile"
        echo "  ./docker-troubleshoot.sh dev              - Setup development environment"
        echo "  ./docker-troubleshoot.sh test             - Run container interactively"
        echo ""
        echo "System checks:"
        echo "  ./docker-troubleshoot.sh requirements     - Check system requirements"
        echo ""
        echo "For the current errors, try:"
        echo -e "${GREEN}./docker-troubleshoot.sh quick-fix${NC}"
        echo ""
        ;;
esac