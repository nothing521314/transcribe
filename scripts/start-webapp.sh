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
