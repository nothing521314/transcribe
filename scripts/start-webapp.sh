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
