#!/bin/bash

# Startup script for Web Application
# Handles initialization, health checks, and graceful shutdown

set -e

# Colors for logging
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Environment setup
log_info "Starting AI Video Subtitle Generator Web App"

# Verify required environment variables
if [ -z "$GEMINI_API_KEY" ]; then
    log_warning "GEMINI_API_KEY not set. AI translation features will be limited."
fi

# Set default values
export FLASK_ENV=${FLASK_ENV:-production}
export DEBUG=${DEBUG:-false}
export PORT=${PORT:-5050}
export WORKERS=${WORKERS:-4}
export TIMEOUT=${TIMEOUT:-300}

log_info "Configuration:"
log_info "  - Flask Environment: $FLASK_ENV"
log_info "  - Debug Mode: $DEBUG"
log_info "  - Port: $PORT"
log_info "  - Workers: $WORKERS"
log_info "  - Request Timeout: ${TIMEOUT}s"

# Create required directories with proper permissions
log_info "Setting up directories..."
mkdir -p uploads output cache temp logs static/uploads
mkdir -p /home/appuser/.cache/whisper

# Fix permissions for whisper cache directory
if [ ! -w "/home/appuser/.cache/whisper" ]; then
    log_warning "Whisper cache directory not writable, trying to fix permissions..."
    chmod -R 755 /home/appuser/.cache 2>/dev/null || log_warning "Could not fix cache permissions"
fi

# Check disk space
log_info "Checking disk space..."
AVAILABLE_SPACE=$(df /app | awk 'NR==2 {print $4}')
AVAILABLE_MB=$((AVAILABLE_SPACE/1024))
if [ "$AVAILABLE_MB" -lt 1024 ]; then  # Less than 1GB
    log_warning "Low disk space available: ${AVAILABLE_MB}MB"
fi

# Pre-load Whisper model if specified
WHISPER_MODEL_SIZE=${WHISPER_MODEL_SIZE:-base}
log_info "Pre-loading Whisper model: $WHISPER_MODEL_SIZE"
python -c "
import whisper
import os
try:
    model = whisper.load_model('$WHISPER_MODEL_SIZE')
    print('✓ Whisper model loaded successfully')
except Exception as e:
    print(f'⚠ Whisper model load failed: {e}')
    print('Model will be downloaded on first use')
" || log_warning "Model pre-loading failed"

# Check external dependencies
log_info "Checking external dependencies..."

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    log_error "FFmpeg not found! Audio/video processing will fail."
    exit 1
fi

# Check gunicorn
if ! command -v gunicorn &> /dev/null; then
    log_error "Gunicorn not found! Production server cannot start."
    log_info "Falling back to development server..."
    export USE_DEV_SERVER=true
else
    log_success "Gunicorn found"
fi

# Test Gemini API if key is provided
if [ ! -z "$GEMINI_API_KEY" ] && [ "$GEMINI_API_KEY" != "your_gemini_api_key_here" ]; then
    log_info "Testing Gemini API connection..."
    python -c "
import google.generativeai as genai
import os
try:
    genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
    model = genai.GenerativeModel('gemini-pro')
    print('✓ Gemini API configured successfully')
except Exception as e:
    print(f'⚠ Gemini API configuration warning: {e}')
"
fi

# Clean up old temporary files
log_info "Cleaning up temporary files..."
find temp/ -name "*.tmp" -mtime +1 -delete 2>/dev/null || true
find uploads/ -name "*.part" -mtime +1 -delete 2>/dev/null || true

# Clean up old cache files (older than CACHE_EXPIRE_HOURS)
CACHE_EXPIRE_HOURS=${CACHE_EXPIRE_HOURS:-24}
log_info "Cleaning cache files older than ${CACHE_EXPIRE_HOURS} hours..."
if command -v python3 &> /dev/null; then
    python3 -c "
import os
import time
cache_dir = 'cache'
expire_time = time.time() - ($CACHE_EXPIRE_HOURS * 3600)
if os.path.exists(cache_dir):
    for file in os.listdir(cache_dir):
        file_path = os.path.join(cache_dir, file)
        if file.endswith('.pkl') and os.path.getmtime(file_path) < expire_time:
            try:
                os.remove(file_path)
                print(f'Removed old cache: {file}')
            except:
                pass
"
fi

# Set up signal handlers for graceful shutdown
shutdown_handler() {
    log_info "Received shutdown signal. Cleaning up..."
    
    # Kill background processes if any
    jobs -p | xargs -r kill 2>/dev/null || true
    
    # Clean up temporary files
    rm -rf temp/*.tmp 2>/dev/null || true
    
    log_success "Cleanup completed. Shutting down."
    exit 0
}

# Trap signals
trap shutdown_handler SIGTERM SIGINT

# Function to check application health
check_health() {
    local max_attempts=30
    local attempt=1
    
    log_info "Waiting for application to start..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -f -s "http://localhost:$PORT/api/stats" > /dev/null 2>&1; then
            log_success "Application is healthy and ready to serve requests"
            return 0
        fi
        
        if [ $((attempt % 5)) -eq 0 ]; then
            log_info "Health check attempt $attempt/$max_attempts, still waiting..."
        fi
        sleep 2
        attempt=$((attempt + 1))
    done
    
    log_error "Application failed to start within expected time"
    return 1
}

# Start the application based on environment
if [ "$FLASK_ENV" = "development" ] || [ "$DEBUG" = "true" ] || [ "$USE_DEV_SERVER" = "true" ]; then
    log_info "Starting in development mode..."
    
    # Development server with auto-reload
    python web_app.py &
    APP_PID=$!
    
    # Wait a bit for the server to start
    sleep 5
    
    # Check if the process is still running
    if ! kill -0 $APP_PID 2>/dev/null; then
        log_error "Application failed to start in development mode"
        exit 1
    fi
    
    log_success "Development server started with PID: $APP_PID"
    
else
    log_info "Starting in production mode with Gunicorn..."
    
    # Production server with Gunicorn
    exec gunicorn \
        --bind 0.0.0.0:$PORT \
        --workers $WORKERS \
        --worker-class gevent \
        --worker-connections 1000 \
        --timeout $TIMEOUT \
        --keepalive 2 \
        --max-requests 1000 \
        --max-requests-jitter 100 \
        --preload \
        --log-level info \
        --access-logfile - \
        --error-logfile - \
        --capture-output \
        --enable-stdio-inheritance \
        web_app:app &
    
    APP_PID=$!
fi

# Check application health in background
check_health &
HEALTH_CHECK_PID=$!

# Wait for the application process
wait $APP_PID
EXIT_CODE=$?

# Kill health check if still running
kill $HEALTH_CHECK_PID 2>/dev/null || true

log_info "Application exited with code: $EXIT_CODE"
exit $EXIT_CODE