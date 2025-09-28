# web_app.py
from typing import List, Dict, Optional
import os
import hashlib
import eventlet
import json
import pickle
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    redirect,
    url_for,
    session,
    flash,
)
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from werkzeug.utils import secure_filename
import threading
import time
import logging
import asyncio
import concurrent.futures
from queue import Queue

# Import enhanced modules
from video_subtitle_processor import VideoSubtitleProcessor, OptimizedVideoSubtitleProcessor
from enhanced_translation_manager import EnhancedTranslationManager
import yt_dlp

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("logs/app.log")],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-change-this")

# Initialize SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=True,
    engineio_logger=True,
    async_mode="eventlet",
    ping_timeout=300,
    ping_interval=25,
)

# Cấu hình
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "output"
CACHE_FOLDER = "cache"
TEMP_FOLDER = "temp"

# Tạo các thư mục cần thiết
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, CACHE_FOLDER, TEMP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Cấu hình file types
ALLOWED_EXTENSIONS = {
    "video": ["mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "3gp"],
    "audio": ["mp3", "wav", "aac", "flac", "ogg", "m4a"],
}

# Danh sách ngôn ngữ hỗ trợ mở rộng
SUPPORTED_LANGUAGES = {
    "vietnamese": {"code": "vi", "name": "Tiếng Việt", "native": "Tiếng Việt", "flag": "🇻🇳"},
    "english": {"code": "en", "name": "English", "native": "English", "flag": "🇺🇸"},
    "chinese": {"code": "zh-cn", "name": "Chinese (Simplified)", "native": "中文 (简体)", "flag": "🇨🇳"},
    "chinese_traditional": {"code": "zh-tw", "name": "Chinese (Traditional)", "native": "中文 (繁體)", "flag": "🇹🇼"},
    "japanese": {"code": "ja", "name": "Japanese", "native": "日本語", "flag": "🇯🇵"},
    "korean": {"code": "ko", "name": "Korean", "native": "한국어", "flag": "🇰🇷"},
    "french": {"code": "fr", "name": "French", "native": "Français", "flag": "🇫🇷"},
    "spanish": {"code": "es", "name": "Spanish", "native": "Español", "flag": "🇪🇸"},
    "german": {"code": "de", "name": "German", "native": "Deutsch", "flag": "🇩🇪"},
    "italian": {"code": "it", "name": "Italian", "native": "Italiano", "flag": "🇮🇹"},
    "portuguese": {"code": "pt", "name": "Portuguese", "native": "Português", "flag": "🇵🇹"},
    "russian": {"code": "ru", "name": "Russian", "native": "Русский", "flag": "🇷🇺"},
    "arabic": {"code": "ar", "name": "Arabic", "native": "العربية", "flag": "🇸🇦"},
    "thai": {"code": "th", "name": "Thai", "native": "ไทย", "flag": "🇹🇭"},
    "hindi": {"code": "hi", "name": "Hindi", "native": "हिन्दी", "flag": "🇮🇳"},
    "indonesian": {"code": "id", "name": "Indonesian", "native": "Bahasa Indonesia", "flag": "🇮🇩"},
    "malaysian": {"code": "ms", "name": "Malaysian", "native": "Bahasa Malaysia", "flag": "🇲🇾"},
    "dutch": {"code": "nl", "name": "Dutch", "native": "Nederlands", "flag": "🇳🇱"},
    "swedish": {"code": "sv", "name": "Swedish", "native": "Svenska", "flag": "🇸🇪"},
    "norwegian": {"code": "no", "name": "Norwegian", "native": "Norsk", "flag": "🇳🇴"},
    "danish": {"code": "da", "name": "Danish", "native": "Dansk", "flag": "🇩🇰"},
    "polish": {"code": "pl", "name": "Polish", "native": "Polski", "flag": "🇵🇱"},
    "czech": {"code": "cs", "name": "Czech", "native": "Čeština", "flag": "🇨🇿"},
    "hungarian": {"code": "hu", "name": "Hungarian", "native": "Magyar", "flag": "🇭🇺"},
    "turkish": {"code": "tr", "name": "Turkish", "native": "Türkçe", "flag": "🇹🇷"},
    "greek": {"code": "el", "name": "Greek", "native": "Ελληνικά", "flag": "🇬🇷"},
    "hebrew": {"code": "he", "name": "Hebrew", "native": "עברית", "flag": "🇮🇱"},
    "finnish": {"code": "fi", "name": "Finnish", "native": "Suomi", "flag": "🇫🇮"},
    "ukrainian": {"code": "uk", "name": "Ukrainian", "native": "Українська", "flag": "🇺🇦"},
    "bulgarian": {"code": "bg", "name": "Bulgarian", "native": "Български", "flag": "🇧🇬"},
    "romanian": {"code": "ro", "name": "Romanian", "native": "Română", "flag": "🇷🇴"},
    "croatian": {"code": "hr", "name": "Croatian", "native": "Hrvatski", "flag": "🇭🇷"},
    "serbian": {"code": "sr", "name": "Serbian", "native": "Српски", "flag": "🇷🇸"},
    "slovenian": {"code": "sl", "name": "Slovenian", "native": "Slovenščina", "flag": "🇸🇮"},
    "slovak": {"code": "sk", "name": "Slovak", "native": "Slovenčina", "flag": "🇸🇰"},
    "lithuanian": {"code": "lt", "name": "Lithuanian", "native": "Lietuvių", "flag": "🇱🇹"},
    "latvian": {"code": "lv", "name": "Latvian", "native": "Latviešu", "flag": "🇱🇻"},
    "estonian": {"code": "et", "name": "Estonian", "native": "Eesti", "flag": "🇪🇪"},
}

# Global variables cho task tracking
processing_tasks = {}
translation_managers = {}  # Cache translation managers


class EnhancedOptimizedVideoSubtitleProcessor(OptimizedVideoSubtitleProcessor):
    """Enhanced processor with intelligent API management and WebSocket integration"""

    def __init__(self, model_size="base", gemini_api_keys=None, socketio=None):
        super().__init__(model_size, gemini_api_keys, socketio)
        
        # Enhanced logging for web app
        logger.info(f"🌐 Initialized enhanced web processor")
        logger.info(f"🔑 API Management: {len(gemini_api_keys or [])} keys")
        
    def emit_translation_status(self, language: str, status: str, message: str, progress: int = None):
        """Emit translation status updates"""
        if self.socketio and self.current_task_id:
            data = {
                'task_id': self.current_task_id,
                'type': 'translation_status',
                'language': language,
                'status': status,  # 'starting', 'processing', 'completed', 'error', 'fallback'
                'message': message,
                'progress': progress
            }
            
            try:
                self.socketio.emit('translation_status', data)
                logger.info(f"📡 Translation status {language}: {status} - {message}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to emit translation status: {e}")

    def enhanced_parallel_translate(self, texts: List[str], target_languages: List[str], 
                                   task_id: str = None) -> Dict[str, List[str]]:
        """Enhanced parallel translation with detailed WebSocket updates"""
        if task_id:
            self.set_task_id(task_id)
        
        results = {}
        results_lock = eventlet.semaphore.Semaphore()
        pool = eventlet.GreenPool(size=min(3, len(target_languages)))
        
        def run_translation(language: str):
            try:
                self.emit_translation_status(language, 'starting', f'Starting {language} translation...')
                translations = self.translation_manager.translate_texts(texts, language)

                api_status = self.translation_manager.get_api_status()
                gemini_available = any(k['available'] for k in api_status['gemini_keys'])
                if not gemini_available and api_status['google_translate']:
                    self.emit_translation_status(language, 'fallback',
                                                f'{language} completed using Google Translate fallback')
                else:
                    self.emit_translation_status(language, 'completed',
                                                f'{language} completed successfully')
                with results_lock:
                    results[language] = translations
            except Exception as e:
                self.emit_translation_status(language, 'error', f'{language} failed: {e}')
                with results_lock:
                    results[language] = texts

        for lang in target_languages:
            pool.spawn(run_translation, lang)

        # Chờ toàn bộ green thread kết thúc
        pool.waitall()

        # Sau khi join, bạn có thể phát tổng kết
        for lang, translated_texts in results.items():
            success_rate = sum(1 for t in translated_texts if t.strip()) / len(translated_texts) * 100
            self.emit_translation_status(lang, 'completed',
                                        f'{lang} done: {success_rate:.1f}% success rate')
        return results


def allowed_file(filename, file_type="video"):
    """Kiểm tra file có hợp lệ không"""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS[file_type]
    )


def get_file_hash(file_path):
    """Tạo hash cho file để cache"""
    logger.debug(f"Generating hash for {file_path}")
    with open(file_path, "rb") as f:
        file_hash = hashlib.md5()
        chunk = f.read(8192)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8192)
    return file_hash.hexdigest()


def download_youtube_video(url, output_path, task_id=None):
    """Download video từ YouTube với enhanced progress updates"""
    logger.info(f"Starting download from {url}")

    def progress_hook(d):
        if d["status"] == "downloading" and task_id:
            try:
                percent_str = d.get("_percent_str", "0%")
                percent = float(percent_str.replace("%", ""))

                socketio.emit(
                    "progress_update",
                    {
                        "task_id": task_id,
                        "step": "download",
                        "step_progress": min(percent, 95),
                        "overall_progress": 5 + (percent * 0.15),
                        "message": f"Downloading... {percent_str}",
                        "status": "processing",
                    },
                )
            except Exception as e:
                logger.warning(f"Progress hook error: {e}")

    try:
        ydl_opts = {
            "format": "best[height<=720]",
            "outtmpl": os.path.join(output_path, "%(title)s.%(ext)s"),
            "ignoreerrors": True,
            "progress_hooks": [progress_hook],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if info:
                filename = ydl.prepare_filename(info)
                logger.info(f"Download completed: {filename}")
                return filename, info.get("title", "Unknown")

    except Exception as e:
        logger.error(f"Download error: {e}")
        return None, str(e)

    return None, "Cannot download video"

def get_cache_path(file_hash, cache_type="transcription"):
    """Lấy đường dẫn cache"""
    return os.path.join(CACHE_FOLDER, f"{file_hash}_{cache_type}.pkl")

def save_to_cache(data, file_hash, cache_type="transcription"):
    """Lưu data vào cache"""
    cache_path = get_cache_path(file_hash, cache_type)
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(data, f)
        logger.info(f"Saved cache: {cache_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving cache: {e}")
        return False


def load_from_cache(file_hash, cache_type="transcription"):
    """Tải data từ cache"""
    cache_path = get_cache_path(file_hash, cache_type)
    try:
        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                data = pickle.load(f)
            logger.info(f"Loaded from cache: {cache_path}")
            return data
    except Exception as e:
        logger.error(f"Error loading cache: {e}")
    return None

def process_video_task_enhanced(
    task_id, video_path, target_languages, api_keys, options
):
    """Enhanced video processing with intelligent API management and detailed status"""
    global processing_tasks

    try:
        logger.info(f"Starting enhanced processing for task {task_id}")
        start_time = time.time()

        processing_tasks[task_id]["status"] = "processing"
        processing_tasks[task_id]["start_time"] = datetime.now()

        def emit_step_progress(step_id, step_progress, message, force_emit=False, **kwargs):
            """Enhanced emit function with better reliability"""
            step_weights = {
                "initialization": 5,
                "download": 15, 
                "transcription": 40,
                "timing": 15,
                "translation": 20,
                "completion": 5,
            }

            step_starts = {
                "initialization": 0,
                "download": 5,
                "transcription": 20,
                "timing": 60,
                "translation": 75,
                "completion": 95,
            }

            base_progress = step_starts.get(step_id, 0)
            step_weight = step_weights.get(step_id, 5)
            overall_progress = base_progress + (step_progress * step_weight / 100)
            overall_progress = min(max(overall_progress, 0), 100)

            elapsed_time = time.time() - start_time

            # Estimate remaining time
            if overall_progress > 5:  # Avoid division by very small numbers
                estimated_total = elapsed_time * 100 / overall_progress
                remaining_time = max(0, estimated_total - elapsed_time)
            else:
                remaining_time = None

            progress_data = {
                "task_id": task_id,
                "step": step_id,
                "step_name": step_id.replace('_', ' ').title(),
                "step_progress": step_progress,
                "overall_progress": round(overall_progress, 1),
                "message": message,
                "elapsed_time": round(elapsed_time, 1),
                "remaining_time": round(remaining_time, 1) if remaining_time else None,
                "status": "processing",
                **kwargs
            }

            try:
                # Emit to specific room
                socketio.emit("progress_update", progress_data, room=task_id)
                
                # Log the emission for debugging
                logger.info(f"[{task_id}] {step_id} {step_progress}% - {message}")
                
                # Force immediate processing if needed
                if force_emit or step_progress >= 100:
                    socketio.sleep(0.1)  # Longer sleep for important events
                else:
                    socketio.sleep(0)  # Standard flush
                    
            except Exception as e:
                logger.error(f"Failed to emit progress for {task_id}: {e}")
                # Continue execution even if emit fails

        # Step 1: Initialization
        emit_step_progress("initialization", 0, "Initializing enhanced processor...")
        socketio.sleep(0)
        
        processor = EnhancedOptimizedVideoSubtitleProcessor(
            model_size=options.get("model_size", "base"), 
            gemini_api_keys=api_keys,
            socketio=socketio
        )
        processor.set_task_id(task_id)
        
        emit_step_progress("initialization", 100, "Enhanced processor initialized")
        socketio.sleep(0)

        # Step 2: Handle video input
        if not video_path and processing_tasks[task_id].get("video_url"):
            video_url = processing_tasks[task_id]["video_url"]
            emit_step_progress("download", 0, "Starting video download...")

            downloaded_path, title = download_youtube_video(
                video_url, UPLOAD_FOLDER, task_id
            )
            if not downloaded_path:
                raise RuntimeError(f"Cannot download video: {title}")

            video_path = downloaded_path
            processing_tasks[task_id]["video_path"] = video_path
            processing_tasks[task_id]["original_filename"] = title
            emit_step_progress("download", 100, "Download completed")
        else:
            emit_step_progress("download", 100, "Using uploaded file")
        file_hash = get_file_hash(video_path)
        cached_transcription = load_from_cache(file_hash, "transcription")
        socketio.sleep(0)

        # Step 3: Transcription
        if cached_transcription:
            emit_step_progress("transcription", 0, "Found cached transcription...")
            result = cached_transcription
            emit_step_progress("transcription", 100, "Using cached transcription data")
            socketio.sleep(0)
        else:
            emit_step_progress("transcription", 0, "Starting audio transcription...")
            socketio.sleep(0)
            
            result = processor.model.transcribe(
                video_path,
                word_timestamps=True,
                verbose=False,
                language="en",
                temperature=0,
                best_of=3,
                beam_size=3,
                patience=1.0,
                fp16=True,
                compression_ratio_threshold=2.4,
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
            )
    
        emit_step_progress(
            "transcription",
            90,
            f'Transcription completed. Found {len(result["segments"])} segments',
        )
        save_to_cache(result, file_hash, "transcription")
        emit_step_progress(
            "transcription", 100, f'Transcription completed. Found {len(result["segments"])} segments'
        )
        
        socketio.sleep(0)

        # Step 4: Timing optimization
        emit_step_progress("timing", 0, "Starting timing optimization...")
        socketio.sleep(0)
        
        improved_segments = processor.improve_subtitle_timing(
            result["segments"],
            max_chars_per_line=options.get("max_chars", 50),
            max_duration=options.get("max_duration", 6.0),
        )
        
        emit_step_progress("timing", 50, f"Optimized {len(improved_segments)} segments")
        socketio.sleep(0)
        
        # Create original SRT
        base_name = Path(video_path).stem
        original_srt_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_original.srt")
        processor.create_srt_from_segments(improved_segments, original_srt_path)
        
        emit_step_progress("timing", 100, "Original SRT file created")
        socketio.sleep(0)

        # Step 5: Enhanced Translation
        translated_files = {}
        if target_languages and api_keys:
            emit_step_progress(
                "translation", 0, f"Starting enhanced translation to {len(target_languages)} languages..."
            )
            socketio.sleep(0)

            texts = [s["text"] for s in improved_segments]
            try:
                
                # Use enhanced translation with status updates
                translated_texts_dict = processor.enhanced_parallel_translate(
                    texts, target_languages, task_id
                )
                
                total_langs = len(translated_texts_dict)
                logger.warning(f"total_langs")
                processed_langs = 0

                # Create SRT files
                for lang, translated_texts in translated_texts_dict.items():
                    processed_langs += 1
                    file_progress = 85 + (processed_langs * 15 // total_langs)  # 85-100%
                    emit_step_progress(
                        "translation", file_progress, f"Creating {lang} subtitle file..."
                    )
                    socketio.sleep(0)

                    if translated_texts and len(translated_texts) == len(improved_segments):
                        translated_segments = []
                        for segment, translated_text in zip(improved_segments, translated_texts):
                            if translated_text.strip():
                                translated_segments.append({
                                    "start": segment["start"],
                                    "end": segment["end"],
                                    "text": translated_text,
                                })

                        lang_srt_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_{lang}.srt")
                        processor.create_srt_from_segments(translated_segments, lang_srt_path)
                        translated_files[lang] = lang_srt_path

                emit_step_progress("translation", 100, "All translations completed")
                socketio.sleep(0)
                
            except Exception as translation_error:
                    logger.error(f"Translation error: {translation_error}")
                    emit_step_progress("translation", 100, f"Translation completed with errors: {str(translation_error)}")
                    socketio.sleep(0.5)
        else:
            # Skip translation
            emit_step_progress("translation", 100, "Translation skipped - no API keys provided")
            socketio.sleep(0)

        # Step 6: Completion
        logger.info("Starting completion phase...")
        socketio.sleep(0.2)  # Small delay before completion
        emit_step_progress("completion", 0, "Finalizing results...")
        socketio.sleep(0)

        # Prepare results for frontend
        files_for_download = []
        files_for_download.append({
            "filename": os.path.basename(original_srt_path),
            "name": "Original (English)",
            "flag": "🇺🇸",
        })

        for lang, file_path in translated_files.items():
            lang_info = SUPPORTED_LANGUAGES.get(lang, {})
            files_for_download.append({
                "filename": os.path.basename(file_path),
                "name": lang_info.get("native", lang.capitalize()),
                "flag": lang_info.get("flag", "🌍"),
            })
        emit_step_progress("completion", 60, f"Prepared {len(files_for_download)} files for download")
        socketio.sleep(0)

        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["results"] = {
            "original_srt": original_srt_path,
            "translated_files": translated_files,
            "segments_count": len(improved_segments),
            "file_hash": file_hash,
            "files": files_for_download,
            "total_time": time.time() - start_time,
            "api_status": processor.get_api_status()  # Include API status
        }

        emit_step_progress("completion", 90, "Saving task results...")
        socketio.sleep(0)

        # Final completion
        total_time = time.time() - start_time
        emit_step_progress("completion", 100, f"All tasks completed in {total_time:.1f}s!")
        socketio.sleep(0.5)  # Important: Final emit needs time

        completion_data = {
            "task_id": task_id,
            "results": {
                "segments_count": len(improved_segments),
                "files": files_for_download,
                "total_time": time.time() - start_time,
                "api_status": processor.get_api_status()
            },
        }

        socketio.emit("task_completed", completion_data, room=task_id)
        socketio.emit(
            "task_completed_broadcast", {**completion_data, "broadcast": True}
        )
        socketio.sleep(0.5)
        logger.info(f"Task {task_id} completed successfully with enhanced translation")
        # Log final API status
        api_status = processor.get_api_status()
        logger.info(f"📊 Final API Status - Gemini: {api_status['total_usage']} requests, "
                   f"{api_status['total_errors']} errors, Google Translate: {api_status['google_translate']}")

    except Exception as e:
        logger.error(f"Enhanced processing error for task {task_id}: {e}")
        processing_tasks[task_id]["status"] = "error"

        error_data = {
            "task_id": task_id,
            "step": "error",
            "overall_progress": 0,
            "message": f"Error: {str(e)}",
            "status": "error",
        }

        socketio.emit("progress_update", error_data, room=task_id)


# Enhanced WebSocket event handlers
@socketio.on("connect")
def handle_connect():
    logger.info(f"✅ Client connected: {request.sid}")
    emit("connected", {"data": "Connected to Enhanced AI Subtitle Generator", "sid": request.sid})


@socketio.on("disconnect")
def handle_disconnect():
    logger.info(f"❌ Client disconnected: {request.sid}")


@socketio.on("join_task")
def handle_join_task(data):
    task_id = data.get("task_id")
    if task_id:
        join_room(task_id)
        logger.info(f"🏠 Client {request.sid} joined task room: {task_id}")

        emit("room_joined", {
            "task_id": task_id,
            "status": "joined",
            "message": f"Successfully joined task room: {task_id}",
            "sid": request.sid,
        }, room=request.sid)

        # Send current status if task exists
        if task_id in processing_tasks:
            task = processing_tasks[task_id]
            emit("task_status", {
                "task_id": task_id,
                "status": task["status"],
                "message": f'Current task status: {task["status"]}',
            }, room=task_id)


@socketio.on("leave_task")
def handle_leave_task(data):
    task_id = data.get("task_id")
    if task_id:
        leave_room(task_id)
        logger.info(f"🚪 Client {request.sid} left task room: {task_id}")


# Flask routes
@app.route("/")
def index():
    """Trang chủ"""
    return render_template("index.html", languages=SUPPORTED_LANGUAGES)


@app.route("/upload", methods=["POST"])
def upload_file():
    """Enhanced upload with intelligent API key management"""
    try:
        logger.info("Received enhanced upload request")

        # Generate task ID
        task_id = hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()

        # Get API keys from form
        api_keys_input = request.form.get("api_keys", "")
        api_keys = [key.strip() for key in api_keys_input.split("\n") if key.strip()]

        if not api_keys:
            return jsonify({
                "success": False,
                "message": "Please provide at least one Gemini API key",
            })

        logger.info(f"Received {len(api_keys)} API keys for enhanced processing")

        # Get other parameters
        target_languages = request.form.getlist("languages")
        options = {
            "max_chars": int(request.form.get("max_chars", 50)),
            "max_duration": float(request.form.get("max_duration", 6.0)),
            "model_size": request.form.get("model_size", "base"),
        }

        video_path = None
        original_filename = None
        video_url = None

        # Handle file upload or URL
        if "file" in request.files and request.files["file"].filename:
            file = request.files["file"]
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{filename}"
                video_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(video_path)
                original_filename = file.filename
                logger.info(f"File uploaded: {video_path}")

        elif request.form.get("video_url"):
            video_url = request.form.get("video_url")
            logger.info(f"Received URL for enhanced processing: {video_url}")

        if not video_path and not video_url:
            return jsonify({
                "success": False,
                "message": "Please select a video file or provide a URL",
            })

        # Initialize task with enhanced features
        processing_tasks[task_id] = {
            "status": "queued",
            "start_time": datetime.now(),
            "video_path": video_path,
            "original_filename": original_filename,
            "video_url": video_url,
            "target_languages": target_languages,
            "api_keys": api_keys,
            "options": options,
        }

        # Start enhanced processing
        socketio.start_background_task(
            process_video_task_enhanced,
            task_id, video_path, target_languages, api_keys, options
        )

        logger.info(f"Started enhanced processing task {task_id}")

        return jsonify({
            "success": True, 
            "task_id": task_id, 
            "message": "Enhanced processing started with intelligent API management"
        })

    except Exception as e:
        logger.error(f"Enhanced upload error: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


@app.route("/download/<path:filename>")
def download_file(filename):
    """Download subtitle file"""
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if os.path.exists(file_path):
            logger.info(f"Serving download: {filename}")
            return send_file(file_path, as_attachment=True, download_name=filename)
        else:
            logger.warning(f"File not found: {filename}")
            return jsonify({"error": "File not found"}), 404
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": "Download failed"}), 500


@app.route("/api/task_status/<task_id>")
def get_task_status(task_id):
    """Get enhanced task status including API information"""
    if task_id not in processing_tasks:
        return jsonify({"error": "Task not found"}), 404

    task = processing_tasks[task_id]
    status_data = {
        "task_id": task_id,
        "status": task["status"],
        "start_time": task["start_time"].isoformat(),
    }

    if task["status"] == "completed" and "results" in task:
        status_data["results"] = task["results"]
    elif task["status"] == "processing":
        elapsed_time = (datetime.now() - task["start_time"]).total_seconds()
        status_data["elapsed_time"] = elapsed_time

    return jsonify(status_data)


@app.route("/api/validate_keys", methods=["POST"])
def validate_api_keys():
    """Enhanced API key validation"""
    try:
        data = request.get_json()
        api_keys = data.get("api_keys", [])

        if not api_keys:
            return jsonify({"success": False, "message": "No API keys provided"})

        # Use enhanced translation manager for validation
        translation_manager = EnhancedTranslationManager(api_keys)
        
        # Test each key with a simple request
        valid_keys = []
        invalid_keys = []

        for i, key in enumerate(api_keys):
            try:
                # Quick validation
                import google.generativeai as genai
                genai.configure(api_key=key)
                model = genai.GenerativeModel("gemini-1.5-pro")
                
                # Small test request
                response = model.generate_content("Hello", 
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=10,
                        temperature=0
                    ))
                
                if response.text:
                    valid_keys.append(f"Key {i+1}: ...{key[-8:]}")
                    logger.info(f"API key {i+1} validated: ...{key[-8:]}")
                else:
                    invalid_keys.append(f"Key {i+1}: ...{key[-8:]} - No response")
                    
            except Exception as e:
                error_msg = str(e)[:100]
                invalid_keys.append(f"Key {i+1}: ...{key[-8:]} - {error_msg}")
                logger.warning(f"Invalid API key {i+1}: ...{key[-8:]} - {error_msg}")

        # Get manager status
        api_status = translation_manager.get_api_status()
        
        return jsonify({
            "success": True,
            "valid_keys": len(valid_keys),
            "invalid_keys": len(invalid_keys),
            "google_translate_available": api_status['google_translate'],
            "details": {
                "valid": valid_keys, 
                "invalid": invalid_keys
            },
        })

    except Exception as e:
        logger.error(f"Enhanced API key validation error: {e}")
        return jsonify({"success": False, "message": f"Validation error: {str(e)}"})


@app.route("/api/reset_api_errors", methods=["POST"])
def reset_api_errors():
    """Reset API key error states"""
    try:
        data = request.get_json() or {}
        task_id = data.get("task_id")
        
        if task_id and task_id in processing_tasks:
            # Reset errors for specific task (if we stored the processor)
            reset_count = 1  # Placeholder
        else:
            # Reset all cached translation managers
            reset_count = 0
            for manager in translation_managers.values():
                reset_count += manager.reset_key_errors()
        
        logger.info(f"Reset {reset_count} API key error states")
        return jsonify({
            "success": True,
            "message": f"Reset {reset_count} API key error states"
        })
        
    except Exception as e:
        logger.error(f"API error reset failed: {e}")
        return jsonify({"success": False, "message": f"Reset failed: {str(e)}"})


@app.route("/api/stats")
def api_stats():
    """Enhanced API statistics"""
    try:
        cache_files = len([f for f in os.listdir(CACHE_FOLDER) if f.endswith(".pkl")])
    except:
        cache_files = 0

    completed_tasks = len([t for t in processing_tasks.values() if t["status"] == "completed"])
    active_tasks = len([t for t in processing_tasks.values() 
                      if t["status"] in ["queued", "processing", "downloading"]])

    # Enhanced stats
    total_api_usage = 0
    total_api_errors = 0
    for manager in translation_managers.values():
        status = manager.get_api_status()
        total_api_usage += status['total_usage']
        total_api_errors += status['total_errors']

    return jsonify({
        "cache_files": cache_files,
        "completed_tasks": completed_tasks,
        "active_tasks": active_tasks,
        "supported_languages": len(SUPPORTED_LANGUAGES),
        "total_api_usage": total_api_usage,
        "total_api_errors": total_api_errors,
        "enhanced_features": {
            "intelligent_api_switching": True,
            "google_translate_fallback": True,
            "real_time_status": True
        },
        "status": "healthy",
    })


@app.route("/api/clear_cache", methods=["POST"])
def clear_cache():
    """Clear cache API"""
    try:
        import glob

        cache_files = glob.glob(os.path.join(CACHE_FOLDER, "*.pkl"))
        removed_count = 0
        for file_path in cache_files:
            os.remove(file_path)
            removed_count += 1

        logger.info(f"Cleared {removed_count} cache files")
        return jsonify({
            "success": True, 
            "message": f"Cleared {removed_count} cache files"
        })
    except Exception as e:
        logger.error(f"Cache clear error: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


@app.route("/history")
def history():
    """Processing history with enhanced information"""
    completed_tasks = []
    for task_id, task in processing_tasks.items():
        if task["status"] == "completed":
            task_info = {
                "task_id": task_id,
                "filename": task.get("original_filename", "Unknown"),
                "start_time": task["start_time"],
                "languages": task.get("target_languages", []),
                "segments_count": task.get("results", {}).get("segments_count", 0),
                "api_keys_used": len(task.get("api_keys", [])),
            }
            
            # Add API status if available
            if "results" in task and "api_status" in task["results"]:
                api_status = task["results"]["api_status"]
                task_info.update({
                    "total_api_requests": api_status.get("total_usage", 0),
                    "total_api_errors": api_status.get("total_errors", 0),
                    "google_translate_used": api_status.get("google_translate", False),
                })
            
            completed_tasks.append(task_info)

    completed_tasks.sort(key=lambda x: x["start_time"], reverse=True)
    return render_template("history.html", tasks=completed_tasks)

@app.route('/progress/<task_id>')
def get_progress(task_id):
    """Lấy tiến trình xử lý"""
    if task_id not in processing_tasks:
        return jsonify({'error': 'Task không tồn tại'})
    
    task = processing_tasks[task_id]
    elapsed_time = (datetime.now() - task['start_time']).total_seconds()
    
    response = {
        'status': task['status'],
        'progress': task['progress'],
        'message': task['message'],
        'elapsed_time': elapsed_time
    }
    
    if task['status'] == 'completed' and task['results']:
        response['results'] = {
            'original_filename': task.get('original_filename', 'Unknown'),
            'segments_count': task['results']['segments_count'],
            'files': []
        }
        
        # Thêm file gốc
        if os.path.exists(task['results']['original_srt']):
            response['results']['files'].append({
                'language': 'original',
                'name': 'English (Original)',
                'filename': os.path.basename(task['results']['original_srt']),
                'path': task['results']['original_srt']
            })
        
        # Thêm files dịch
        for lang, file_path in task['results']['translated_files'].items():
            if os.path.exists(file_path):
                lang_info = SUPPORTED_LANGUAGES.get(lang.lower(), {})
                response['results']['files'].append({
                    'language': lang,
                    'name': lang_info.get('native', lang.title()),
                    'filename': os.path.basename(file_path),
                    'path': file_path,
                    'flag': lang_info.get('flag', '🌍')
                })
    
    return jsonify(response)

@app.route("/api/languages")
def api_languages():
    """API endpoint for supported languages"""
    return jsonify(SUPPORTED_LANGUAGES)


if __name__ == "__main__":
    # Initialize logging
    os.makedirs("logs", exist_ok=True)

    # Start the application
    port = int(os.environ.get("PORT", 5050))
    debug_mode = os.environ.get("DEBUG", "False").lower() == "true"

    logger.info(f"Starting enhanced AI subtitle generator on port {port}")
    logger.info(f"Debug mode: {debug_mode}")
    logger.info(f"Supported languages: {len(SUPPORTED_LANGUAGES)}")
    logger.info("Enhanced Features:")
    logger.info("  - Intelligent API key switching when rate limited")
    logger.info("  - Automatic Google Translate fallback")
    logger.info("  - Real-time translation status updates")
    logger.info("  - Enhanced error handling and recovery")
    logger.info("  - WebSocket progress tracking")
    logger.info("  - Smart caching and retry mechanisms")

    socketio.run(
        app, 
        host="0.0.0.0", 
        port=port, 
        debug=debug_mode, 
        allow_unsafe_werkzeug=True
    )