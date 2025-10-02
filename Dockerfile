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

COPY web_app.py video_subtitle_processor.py enhanced_translation_manager.py subtitle_enhancer.py ./
COPY shared_state.py __init__.py ./ 
COPY templates/ templates/
COPY routes/ routes/
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
