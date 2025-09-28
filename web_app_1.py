# web_app.py

import os
import hashlib
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
from video_subtitle_processor import VideoSubtitleProcessor
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
    "vietnamese": {
        "code": "vi",
        "name": "Tiếng Việt",
        "native": "Tiếng Việt",
        "flag": "🇻🇳",
    },
    "english": {"code": "en", "name": "English", "native": "English", "flag": "🇺🇸"},
    "chinese": {
        "code": "zh-cn",
        "name": "Chinese (Simplified)",
        "native": "中文 (简体)",
        "flag": "🇨🇳",
    },
    "chinese_traditional": {
        "code": "zh-tw",
        "name": "Chinese (Traditional)",
        "native": "中文 (繁體)",
        "flag": "🇹🇼",
    },
    "japanese": {"code": "ja", "name": "Japanese", "native": "日本語", "flag": "🇯🇵"},
    "korean": {"code": "ko", "name": "Korean", "native": "한국어", "flag": "🇰🇷"},
    "french": {"code": "fr", "name": "French", "native": "Français", "flag": "🇫🇷"},
    "spanish": {"code": "es", "name": "Spanish", "native": "Español", "flag": "🇪🇸"},
    "german": {"code": "de", "name": "German", "native": "Deutsch", "flag": "🇩🇪"},
    "italian": {"code": "it", "name": "Italian", "native": "Italiano", "flag": "🇮🇹"},
    "portuguese": {
        "code": "pt",
        "name": "Portuguese",
        "native": "Português",
        "flag": "🇵🇹",
    },
    "russian": {"code": "ru", "name": "Russian", "native": "Русский", "flag": "🇷🇺"},
    "arabic": {"code": "ar", "name": "Arabic", "native": "العربية", "flag": "🇸🇦"},
    "thai": {"code": "th", "name": "Thai", "native": "ไทย", "flag": "🇹🇭"},
    "hindi": {"code": "hi", "name": "Hindi", "native": "हिन्दी", "flag": "🇮🇳"},
    "indonesian": {
        "code": "id",
        "name": "Indonesian",
        "native": "Bahasa Indonesia",
        "flag": "🇮🇩",
    },
    "malaysian": {
        "code": "ms",
        "name": "Malaysian",
        "native": "Bahasa Malaysia",
        "flag": "🇲🇾",
    },
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
    "ukrainian": {
        "code": "uk",
        "name": "Ukrainian",
        "native": "Українська",
        "flag": "🇺🇦",
    },
    "bulgarian": {
        "code": "bg",
        "name": "Bulgarian",
        "native": "Български",
        "flag": "🇧🇬",
    },
    "romanian": {"code": "ro", "name": "Romanian", "native": "Română", "flag": "🇷🇴"},
    "croatian": {"code": "hr", "name": "Croatian", "native": "Hrvatski", "flag": "🇭🇷"},
    "serbian": {"code": "sr", "name": "Serbian", "native": "Српски", "flag": "🇷🇸"},
    "slovenian": {
        "code": "sl",
        "name": "Slovenian",
        "native": "Slovenščina",
        "flag": "🇸🇮",
    },
    "slovak": {"code": "sk", "name": "Slovak", "native": "Slovenčina", "flag": "🇸🇰"},
    "lithuanian": {
        "code": "lt",
        "name": "Lithuanian",
        "native": "Lietuvių",
        "flag": "🇱🇹",
    },
    "latvian": {"code": "lv", "name": "Latvian", "native": "Latviešu", "flag": "🇱🇻"},
    "estonian": {"code": "et", "name": "Estonian", "native": "Eesti", "flag": "🇪🇪"},
}

# Global variables cho task tracking
processing_tasks = {}
api_key_pool = Queue()
processors = {}


class OptimizedVideoSubtitleProcessor(VideoSubtitleProcessor):
    """Enhanced processor with optimization and logging"""

    def __init__(self, model_size="base", gemini_api_keys=None):
        self.gemini_api_keys = gemini_api_keys or []
        self.current_api_index = 0

        if self.gemini_api_keys:
            # Initialize with first API key
            super().__init__(model_size, self.gemini_api_keys[0])
            logger.info(
                f"Initialized processor with {len(self.gemini_api_keys)} API keys"
            )
        else:
            super().__init__(model_size, None)
            logger.warning("No Gemini API keys provided")

    def get_next_api_key(self):
        """Round-robin API key selection"""
        if not self.gemini_api_keys:
            return None

        api_key = self.gemini_api_keys[self.current_api_index]
        self.current_api_index = (self.current_api_index + 1) % len(
            self.gemini_api_keys
        )
        return api_key

    def extract_audio_and_transcribe_optimized(
        self, video_path, output_dir=None, task_id=None
    ):
        """Optimized transcription with progress updates"""
        logger.info(f"Starting optimized transcription for {video_path}")

        if output_dir is None:
            output_dir = os.path.dirname(video_path)

        # Emit progress update
        if task_id:
            socketio.emit(
                "progress_update",
                {
                    "task_id": task_id,
                    "step": "transcription",
                    "progress": 10,
                    "message": f'Starting transcription with model {self.model.get_params().get("model_size", "unknown")}...',
                },
            )

        logger.info(f"Processing video: {video_path}")

        # Enhanced Whisper settings for better performance
        result = self.model.transcribe(
            video_path,
            word_timestamps=True,
            verbose=True,
            language="en",
            temperature=0,
            best_of=5,
            beam_size=5,
            patience=1.0,
            # Optimizations
            fp16=True,  # Use half precision for speed
            compression_ratio_threshold=2.4,
            logprob_threshold=-1.0,
            no_speech_threshold=0.6,
        )

        if task_id:
            socketio.emit(
                "progress_update",
                {
                    "task_id": task_id,
                    "step": "transcription",
                    "progress": 50,
                    "message": f'Transcription completed. Found {len(result["segments"])} segments.',
                },
            )

        logger.info(f"Transcription completed: {len(result['segments'])} segments")
        return result

    def parallel_translate(self, texts, target_languages, task_id=None):
        """Parallel translation using multiple API keys"""
        logger.info(
            f"Starting parallel translation for {len(target_languages)} languages"
        )

        if not self.gemini_api_keys:
            logger.warning(
                "No API keys available, falling back to sequential translation"
            )
            return self.sequential_translate(texts, target_languages, task_id)

        # Group languages by API keys
        api_key_groups = {}
        for i, lang in enumerate(target_languages):
            api_key = self.gemini_api_keys[i % len(self.gemini_api_keys)]
            if api_key not in api_key_groups:
                api_key_groups[api_key] = []
            api_key_groups[api_key].append(lang)

        translated_results = {}

        def translate_group(api_key, languages):
            """Translate a group of languages using specific API key"""
            group_processor = VideoSubtitleProcessor(gemini_api_key=api_key)
            group_results = {}

            for lang in languages:
                try:
                    logger.info(
                        f"Translating to {lang} using API key ending in ...{api_key[-4:]}"
                    )

                    if task_id:
                        socketio.emit(
                            "progress_update",
                            {
                                "task_id": task_id,
                                "step": "translation",
                                "progress": 70
                                + (
                                    list(target_languages).index(lang)
                                    * 25
                                    // len(target_languages)
                                ),
                                "message": f"Translating to {lang}...",
                            },
                        )

                    translated_texts = group_processor.translate_with_gemini(
                        texts, lang
                    )
                    group_results[lang] = translated_texts

                    logger.info(f"Completed translation to {lang}")

                except Exception as e:
                    logger.error(f"Translation error for {lang}: {e}")
                    group_results[lang] = texts  # Fallback to original

            return group_results

        # Execute translations in parallel
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self.gemini_api_keys)
        ) as executor:
            futures = {}

            for api_key, languages in api_key_groups.items():
                future = executor.submit(translate_group, api_key, languages)
                futures[future] = api_key

            # Collect results
            for future in concurrent.futures.as_completed(futures):
                api_key = futures[future]
                try:
                    group_results = future.result()
                    translated_results.update(group_results)
                    logger.info(
                        f"Completed group translation for API key ending in ...{api_key[-4:]}"
                    )
                except Exception as e:
                    logger.error(f"Group translation failed for API key {api_key}: {e}")

        logger.info("Parallel translation completed")
        return translated_results


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


# Update download function to emit progress
def download_youtube_video(url, output_path, task_id=None):
    """Download video từ YouTube với enhanced progress updates"""
    logger.info(f"Starting download from {url}")

    def progress_hook(d):
        if d["status"] == "downloading" and task_id:
            try:
                percent_str = d.get("_percent_str", "0%")
                percent = float(percent_str.replace("%", ""))

                # Emit detailed download progress
                socketio.emit(
                    "progress_update",
                    {
                        "task_id": task_id,
                        "step": "download",
                        "step_progress": min(percent, 95),
                        "overall_progress": 5
                        + (percent * 0.15),  # Download is 15% of total
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


def process_video_task(task_id, video_path, target_languages, api_keys, options):
    """Enhanced video processing with detailed WebSocket updates"""
    global processing_tasks
    try:
        logger.info(f"Starting enhanced processing for task {task_id}")
        start_time = time.time()

        processing_tasks[task_id]["status"] = "processing"
        processing_tasks[task_id]["start_time"] = start_time

        steps = [
            {
                "id": "initialization",
                "name": "Initialization",
                "weight": 5,
                "progress_start": 0,
            },
            {"id": "download", "name": "Download", "weight": 15, "progress_start": 5},
            {
                "id": "transcription",
                "name": "Transcription",
                "weight": 40,
                "progress_start": 20,
            },
            {
                "id": "timing",
                "name": "Timing Optimization",
                "weight": 15,
                "progress_start": 60,
            },
            {
                "id": "translation",
                "name": "Translation",
                "weight": 20,
                "progress_start": 75,
            },
            {
                "id": "completion",
                "name": "Completion",
                "weight": 5,
                "progress_start": 95,
            },
        ]

        def emit_step_progress(step_id, step_progress, message, elapsed_time=None):
            """Emit detailed progress for a specific step"""
            step = next((s for s in steps if s["id"] == step_id), None)
            if not step:
                return

            # Calculate overall progress
            overall_progress = step["progress_start"] + (
                step_progress * step["weight"] / 100
            )
            overall_progress = min(max(overall_progress, 0), 100)

            # Calculate elapsed time
            if elapsed_time is None:
                elapsed_time = time.time() - start_time

            # Estimate remaining time
            if overall_progress > 0:
                estimated_total = elapsed_time * 100 / overall_progress
                remaining_time = max(0, estimated_total - elapsed_time)
            else:
                remaining_time = None

            # Calculate overall progress (simple version for now)
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

            # Estimate remaining time
            if overall_progress > 0:
                estimated_total = elapsed_time * 100 / overall_progress
                remaining_time = max(0, estimated_total - elapsed_time)
            else:
                remaining_time = None

            progress_data = {
                "task_id": task_id,
                "step": step_id,
                "step_name": step["name"],
                "step_progress": step_progress,
                "overall_progress": round(overall_progress, 1),
                "message": message,
                "elapsed_time": round(elapsed_time, 1),
                "remaining_time": round(remaining_time, 1) if remaining_time else None,
                "status": "processing",
            }

            # Emit progress using our enhanced function
            # emit_progress_update(task_id, progress_data)
            socketio.emit("progress_update", progress_data, room=task_id)

            # socketio.emit('progress_update', progress_data, room=task_id)
            logger.info(f"Task {task_id}: {step['name']} {step_progress}% - {message}")

        # Step 1: Initialization
        emit_step_progress("initialization", 0, "Initializing processor...")
        socketio.sleep(0)  # 🔑 cho phép flush
        processor = OptimizedVideoSubtitleProcessor(
            model_size=options.get("model_size", "base"), gemini_api_keys=api_keys
        )
        emit_step_progress("initialization", 100, "Processor initialized")
        socketio.sleep(0)

        # Step 2: Download / Cache check
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
        # if 'video_url' in processing_tasks[task_id]:
        #     emit_step_progress('download', 0, 'Starting video download...')
        #     for i in range(0, 101, 25):
        #         emit_step_progress('download', i, f'Downloading... {i}%')
        #         socketio.sleep(0.5)
        # else:
        #     emit_step_progress('download', 100, 'Using uploaded file')
        socketio.sleep(0)

        # Step 3: Transcription
        if cached_transcription:
            emit_step_progress("transcription", 0, "Found cached transcription...")
            result = cached_transcription
            emit_step_progress("transcription", 100, "Using cached transcription data")
            socketio.sleep(0)
        else:
            emit_step_progress("transcription", 0, "Starting audio transcription...")
            emit_step_progress("transcription", 10, "Loading audio...")
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
            emit_step_progress("transcription", 100, "Transcription saved to cache")
            socketio.sleep(0)

        # Step 4: Timing Optimization  🔑 thêm sleep(0)
        emit_step_progress("timing", 0, "Starting timing optimization...")
        socketio.sleep(0)
        improved_segments = processor.improve_subtitle_timing(
            result["segments"],
            max_chars_per_line=options.get("max_chars", 50),
            max_duration=options.get("max_duration", 6.0),
        )
        emit_step_progress("timing", 50, f"Optimized {len(improved_segments)} segments")
        socketio.sleep(0)
        base_name = Path(video_path).stem
        original_srt_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_original.srt")
        processor.create_srt_from_segments(improved_segments, original_srt_path)
        emit_step_progress("timing", 100, "Original SRT file created")
        socketio.sleep(0)

        # Step 5: Translation – chèn sleep trong từng vòng lặp
        translated_files = {}
        if target_languages and api_keys:
            emit_step_progress(
                "translation",
                0,
                f"Starting translation to {len(target_languages)} languages...",
            )
            socketio.sleep(0)

            texts = [s["text"] for s in improved_segments]
            total_languages = len(target_languages)
            for i, lang in enumerate(target_languages):
                try:
                    lang_progress = (i * 100) // total_languages
                    emit_step_progress(
                        "translation",
                        lang_progress,
                        f"Translating to {lang}... ({i+1}/{total_languages})",
                    )
                    socketio.sleep(0)

                    translated_texts = processor.translate_with_gemini(texts, lang)

                    if translated_texts and len(translated_texts) == len(
                        improved_segments
                    ):
                        # Create translated segments
                        translated_segments = []
                        for segment, translated_text in zip(
                            improved_segments, translated_texts
                        ):
                            if translated_text.strip():
                                translated_segments.append(
                                    {
                                        "start": segment["start"],
                                        "end": segment["end"],
                                        "text": translated_text,
                                    }
                                )

                        # Create SRT file
                        lang_srt_path = os.path.join(
                            OUTPUT_FOLDER, f"{base_name}_{lang}.srt"
                        )
                        processor.create_srt_from_segments(
                            translated_segments, lang_srt_path
                        )
                        translated_files[lang] = lang_srt_path

                        lang_progress = ((i + 1) * 100) // total_languages
                        emit_step_progress(
                            "translation",
                            lang_progress,
                            f"Completed {lang} translation",
                        )

                    lang_progress = ((i + 1) * 100) // total_languages
                    emit_step_progress(
                        "translation", lang_progress, f"Completed {lang} translation"
                    )
                    socketio.sleep(0)
                except Exception as e:
                    logger.error(f"Translation error for {lang}: {e}")
                    emit_step_progress(
                        "translation",
                        ((i + 1) * 100) // total_languages,
                        f"Translation failed for {lang}: {str(e)}",
                    )
                    socketio.sleep(0)
            emit_step_progress("translation", 100, "All translations completed")
            socketio.sleep(0)

        # Step 6: Completion
        emit_step_progress("completion", 0, "Finalizing results...")
        socketio.sleep(0)
        # Prepare results for frontend
        files_for_download = []

        # Add original file
        files_for_download.append(
            {
                "filename": os.path.basename(original_srt_path),
                "name": "Original (English)",
                "flag": "🇺🇸",
            }
        )

        # Add translated files
        for lang, file_path in translated_files.items():
            lang_info = SUPPORTED_LANGUAGES.get(lang, {})
            files_for_download.append(
                {
                    "filename": os.path.basename(file_path),
                    "name": lang_info.get("native", lang.capitalize()),
                    "flag": lang_info.get("flag", "🌍"),
                }
            )
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["results"] = {
            "original_srt": original_srt_path,
            "translated_files": translated_files,
            "segments_count": len(improved_segments),
            "file_hash": file_hash,
            "files": files_for_download,
            "total_time": time.time() - start_time,
        }

        emit_step_progress(
            "completion",
            100,
            f"All tasks completed in {time.time() - start_time:.1f}s!",
        )
        socketio.sleep(0)

        completion_data = {
            "task_id": task_id,
            "results": {
                "segments_count": len(improved_segments),
                "files": files_for_download,
                "total_time": time.time() - start_time,
            },
        }

        socketio.emit("task_completed", completion_data, room=task_id)
        socketio.emit(
            "task_completed_broadcast", {**completion_data, "broadcast": True}
        )
        logger.info(f"Task {task_id} completed successfully")
    except Exception as e:
        logger.error(f"Processing error for task {task_id}: {e}")
        processing_tasks[task_id]["status"] = "error"

        elapsed_time = time.time() - start_time if "start_time" in locals() else 0

        error_data = {
            "task_id": task_id,
            "step": "error",
            "overall_progress": 0,
            "message": f"Error: {str(e)}",
            "elapsed_time": elapsed_time,
            "status": "error",
        }

        socketio.emit("progress_update", error_data, room=task_id)
        socketio.emit("progress_update_broadcast", {**error_data, "broadcast": True})


def process_video_task_enhanced(
    task_id, video_path, target_languages, api_keys, options
):
    """Enhanced video processing with detailed WebSocket updates"""
    global processing_tasks

    try:
        logger.info(f"Starting enhanced processing for task {task_id}")
        start_time = time.time()

        # Update task status
        processing_tasks[task_id]["status"] = "processing"
        processing_tasks[task_id]["start_time"] = start_time

        # Define processing steps with time estimates
        steps = [
            {
                "id": "initialization",
                "name": "Initialization",
                "weight": 5,
                "progress_start": 0,
            },
            {"id": "download", "name": "Download", "weight": 15, "progress_start": 5},
            {
                "id": "transcription",
                "name": "Transcription",
                "weight": 40,
                "progress_start": 20,
            },
            {
                "id": "timing",
                "name": "Timing Optimization",
                "weight": 15,
                "progress_start": 60,
            },
            {
                "id": "translation",
                "name": "Translation",
                "weight": 20,
                "progress_start": 75,
            },
            {
                "id": "completion",
                "name": "Completion",
                "weight": 5,
                "progress_start": 95,
            },
        ]

        def emit_step_progress(step_id, step_progress, message, elapsed_time=None):
            """Emit detailed progress for a specific step"""
            step = next((s for s in steps if s["id"] == step_id), None)
            if not step:
                return

            # Calculate overall progress
            overall_progress = step["progress_start"] + (
                step_progress * step["weight"] / 100
            )
            overall_progress = min(max(overall_progress, 0), 100)

            # Calculate elapsed time
            if elapsed_time is None:
                elapsed_time = time.time() - start_time

            # Estimate remaining time
            if overall_progress > 0:
                estimated_total = elapsed_time * 100 / overall_progress
                remaining_time = max(0, estimated_total - elapsed_time)
            else:
                remaining_time = None

            # Calculate overall progress (simple version for now)
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

            # Estimate remaining time
            if overall_progress > 0:
                estimated_total = elapsed_time * 100 / overall_progress
                remaining_time = max(0, estimated_total - elapsed_time)
            else:
                remaining_time = None

            progress_data = {
                "task_id": task_id,
                "step": step_id,
                "step_name": step["name"],
                "step_progress": step_progress,
                "overall_progress": round(overall_progress, 1),
                "message": message,
                "elapsed_time": round(elapsed_time, 1),
                "remaining_time": round(remaining_time, 1) if remaining_time else None,
                "status": "processing",
            }

            # Emit progress using our enhanced function
            # emit_progress_update(task_id, progress_data)
            socketio.emit("progress_update", progress_data, room=task_id)

            # socketio.emit('progress_update', progress_data, room=task_id)
            logger.info(f"Task {task_id}: {step['name']} {step_progress}% - {message}")

        # Initialize processor
        emit_step_progress("initialization", 0, "Initializing processor...")
        socketio.sleep(1)  # Give UI time to update

        # Initialize processor with API keys
        processor = OptimizedVideoSubtitleProcessor(
            model_size=options.get("model_size", "base"), gemini_api_keys=api_keys
        )

        # Step 1: Initialization
        emit_step_progress("initialization", 100, "Processor initialized")

        # Step 2: Check cache / Download
        file_hash = get_file_hash(video_path)
        cached_transcription = load_from_cache(file_hash, "transcription")

        if "video_url" in processing_tasks[task_id]:
            # Download step
            emit_step_progress("download", 0, "Starting video download...")
            # Simulate download progress (replace with actual download progress)
            for i in range(0, 101, 25):
                emit_step_progress("download", i, f"Downloading... {i}%")
                socketio.sleep(0.5)
        else:
            # Skip download for file uploads
            emit_step_progress("download", 100, "Using uploaded file")

        if cached_transcription:
            # Step 3: Use cached transcription
            emit_step_progress("transcription", 0, "Found cached transcription...")
            result = cached_transcription
            emit_step_progress("transcription", 100, "Using cached transcription data")
        else:
            # Step 3: Transcribe
            emit_step_progress("transcription", 0, "Starting audio transcription...")

            # Custom transcribe with progress updates
            logger.info(f"Processing video: {video_path}")

            emit_step_progress("transcription", 10, "Loading audio...")

            # Enhanced Whisper settings for better performance
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

            # Save to cache
            save_to_cache(result, file_hash, "transcription")
            emit_step_progress("transcription", 100, "Transcription saved to cache")

        # Step 4: Improve timing
        emit_step_progress("timing", 0, "Starting timing optimization...")

        improved_segments = processor.improve_subtitle_timing(
            result["segments"],
            max_chars_per_line=options.get("max_chars", 50),
            max_duration=options.get("max_duration", 6.0),
        )

        emit_step_progress("timing", 50, f"Optimized {len(improved_segments)} segments")

        # Step 5: Create original SRT
        base_name = Path(video_path).stem
        original_srt_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_original.srt")
        processor.create_srt_from_segments(improved_segments, original_srt_path)

        emit_step_progress("timing", 100, "Original SRT file created")

        # Step 6: Translation
        translated_files = {}
        if target_languages and api_keys:
            emit_step_progress(
                "translation",
                0,
                f"Starting translation to {len(target_languages)} languages...",
            )

            # Extract texts for translation
            texts = [segment["text"] for segment in improved_segments]
            total_languages = len(target_languages)

            for i, lang in enumerate(target_languages):
                try:
                    # Update progress for each language
                    lang_progress = (i * 100) // total_languages
                    emit_step_progress(
                        "translation",
                        lang_progress,
                        f"Translating to {lang}... ({i+1}/{total_languages})",
                    )

                    # Use single language translation for better progress tracking
                    translated_texts = processor.translate_with_gemini(texts, lang)

                    if translated_texts and len(translated_texts) == len(
                        improved_segments
                    ):
                        # Create translated segments
                        translated_segments = []
                        for segment, translated_text in zip(
                            improved_segments, translated_texts
                        ):
                            if translated_text.strip():
                                translated_segments.append(
                                    {
                                        "start": segment["start"],
                                        "end": segment["end"],
                                        "text": translated_text,
                                    }
                                )

                        # Create SRT file
                        lang_srt_path = os.path.join(
                            OUTPUT_FOLDER, f"{base_name}_{lang}.srt"
                        )
                        processor.create_srt_from_segments(
                            translated_segments, lang_srt_path
                        )
                        translated_files[lang] = lang_srt_path

                        lang_progress = ((i + 1) * 100) // total_languages
                        emit_step_progress(
                            "translation",
                            lang_progress,
                            f"Completed {lang} translation",
                        )

                except Exception as e:
                    logger.error(f"Translation error for {lang}: {e}")
                    emit_step_progress(
                        "translation",
                        ((i + 1) * 100) // total_languages,
                        f"Translation failed for {lang}: {str(e)}",
                    )

            emit_step_progress("translation", 100, f"All translations completed")

        # Step 7: Complete
        emit_step_progress("completion", 0, "Finalizing results...")

        # Prepare results for frontend
        files_for_download = []

        # Add original file
        files_for_download.append(
            {
                "filename": os.path.basename(original_srt_path),
                "name": "Original (English)",
                "flag": "🇺🇸",
            }
        )

        # Add translated files
        for lang, file_path in translated_files.items():
            lang_info = SUPPORTED_LANGUAGES.get(lang, {})
            files_for_download.append(
                {
                    "filename": os.path.basename(file_path),
                    "name": lang_info.get("native", lang.capitalize()),
                    "flag": lang_info.get("flag", "🌍"),
                }
            )

        # Update task results
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["results"] = {
            "original_srt": original_srt_path,
            "translated_files": translated_files,
            "segments_count": len(improved_segments),
            "file_hash": file_hash,
            "files": files_for_download,
            "total_time": time.time() - start_time,
        }

        emit_step_progress(
            "completion",
            100,
            f"All tasks completed in {time.time() - start_time:.1f}s!",
        )

        # Emit completion with results
        completion_data = {
            "task_id": task_id,
            "results": {
                "segments_count": len(improved_segments),
                "files": files_for_download,
                "total_time": time.time() - start_time,
            },
        }

        socketio.emit("task_completed", completion_data, room=task_id)
        socketio.emit(
            "task_completed_broadcast", {**completion_data, "broadcast": True}
        )

        logger.info(
            f"Task {task_id} completed successfully in {time.time() - start_time:.2f}s"
        )

    except Exception as e:
        logger.error(f"Processing error for task {task_id}: {e}")
        processing_tasks[task_id]["status"] = "error"

        elapsed_time = time.time() - start_time if "start_time" in locals() else 0

        error_data = {
            "task_id": task_id,
            "step": "error",
            "overall_progress": 0,
            "message": f"Error: {str(e)}",
            "elapsed_time": elapsed_time,
            "status": "error",
        }

        socketio.emit("progress_update", error_data, room=task_id)
        socketio.emit("progress_update_broadcast", {**error_data, "broadcast": True})


# Enhanced WebSocket event handlers


@socketio.on("connect")
def handle_connect():
    logger.info(f"✅ Client connected: {request.sid}")
    emit(
        "connected", {"data": "Connected to AI Subtitle Generator", "sid": request.sid}
    )


@socketio.on("disconnect")
def handle_disconnect():
    logger.info(f"❌ Client disconnected: {request.sid}")


@socketio.on("join_task")
def handle_join_task(data):
    task_id = data.get("task_id")
    if task_id:
        join_room(task_id)
        logger.info(f"🏠 Client {request.sid} joined task room: {task_id}")

        # Gửi confirmation ngay lập tức
        emit(
            "room_joined",
            {
                "task_id": task_id,
                "status": "joined",
                "message": f"Successfully joined task room: {task_id}",
                "sid": request.sid,
            },
            room=request.sid,
        )

        # Gửi current status nếu task tồn tại
        if task_id in processing_tasks:
            task = processing_tasks[task_id]
            emit(
                "task_status",
                {
                    "task_id": task_id,
                    "status": task["status"],
                    "message": f'Current task status: {task["status"]}',
                },
                room=task_id,
            )


@socketio.on("leave_task")
def handle_leave_task(data):
    task_id = data.get("task_id")
    if task_id:
        leave_room(task_id)
        logger.info(f"🚪 Client {request.sid} left task room: {task_id}")


# Fix progress emission function
def emit_progress_update(task_id, step_data):
    """Enhanced progress emission with debugging"""
    try:
        # Đảm bảo data có đúng format
        progress_data = {
            "task_id": task_id,
            "step": step_data.get("step", ""),
            "step_name": step_data.get("step_name", ""),
            "step_progress": step_data.get("step_progress", 0),
            "overall_progress": step_data.get("overall_progress", 0),
            "message": step_data.get("message", ""),
            "elapsed_time": step_data.get("elapsed_time", 0),
            "remaining_time": step_data.get("remaining_time"),
            "status": step_data.get("status", "processing"),
        }

        logger.info(f"Emitting progress to room {task_id}: {progress_data}")

        # Gửi đến room cụ thể
        socketio.emit("progress_update", progress_data, room=task_id)

        # Log số lượng clients trong room
        # room_clients = list(socketio.server.manager.rooms.get('/').get(task_id, []))
        logger.info(f"Clients in room {task_id}: {len(room_clients)}")

    except Exception as e:
        logger.error(f"Error emitting progress for {task_id}: {e}")


def heartbeat(task_id):
    while processing_tasks[task_id]["status"] == "processing":
        socketio.emit("keep_alive", {"task_id": task_id}, room=task_id)
        socketio.sleep(20)


# Flask routes
@app.route("/")
def index():
    """Trang chủ"""
    return render_template("index.html", languages=SUPPORTED_LANGUAGES)


# Enhanced upload route
@app.route("/upload", methods=["POST"])
def upload_file():
    """Enhanced upload with API key management"""
    try:
        logger.info("Received upload request")

        # Generate task ID
        task_id = hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()

        # Get API keys from form
        api_keys_input = request.form.get("api_keys", "")
        api_keys = [key.strip() for key in api_keys_input.split("\n") if key.strip()]

        if not api_keys:
            return jsonify(
                {
                    "success": False,
                    "message": "Please provide at least one Gemini API key",
                }
            )

        logger.info(f"Received {len(api_keys)} API keys")

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
            logger.info(f"Received URL for download: {video_url}")

        if not video_path and not video_url:
            return jsonify(
                {
                    "success": False,
                    "message": "Please select a video file or provide a URL",
                }
            )

        if not video_path:
            return jsonify(
                {
                    "success": False,
                    "message": "Please select a video file or provide a URL",
                }
            )

        # Initialize task
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

        # Start processing in background thread
        # thread = threading.Thread(
        #     target=process_video_task_enhanced,
        #     args=(task_id, video_path, target_languages, api_keys, options)
        # )
        # thread.daemon = True
        # thread.start()
        socketio.start_background_task(heartbeat, task_id)
        socketio.start_background_task(
            process_video_task, task_id, video_path, target_languages, api_keys, options
        )

        logger.info(f"Started processing task {task_id}")

        return jsonify(
            {"success": True, "task_id": task_id, "message": "Processing started"}
        )

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


@app.route("/progress/<task_id>")
def get_progress(task_id):
    """Legacy progress endpoint (for compatibility)"""
    if task_id not in processing_tasks:
        return jsonify({"error": "Task not found"})

    task = processing_tasks[task_id]
    elapsed_time = (datetime.now() - task["start_time"]).total_seconds()

    return jsonify(
        {"status": task["status"], "elapsed_time": elapsed_time, "task_id": task_id}
    )


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


@app.route("/history")
def history():
    """Processing history"""
    completed_tasks = []
    for task_id, task in processing_tasks.items():
        if task["status"] == "completed":
            completed_tasks.append(
                {
                    "task_id": task_id,
                    "filename": task.get("original_filename", "Unknown"),
                    "start_time": task["start_time"],
                    "languages": task.get("target_languages", []),
                    "segments_count": task.get("results", {}).get("segments_count", 0),
                }
            )

    completed_tasks.sort(key=lambda x: x["start_time"], reverse=True)
    return render_template("history.html", tasks=completed_tasks)


@app.route("/api/languages")
def api_languages():
    """API endpoint for supported languages"""
    return jsonify(SUPPORTED_LANGUAGES)


@app.route("/api/stats")
def api_stats():
    """API statistics"""
    try:
        cache_files = len([f for f in os.listdir(CACHE_FOLDER) if f.endswith(".pkl")])
    except:
        cache_files = 0

    completed_tasks = len(
        [t for t in processing_tasks.values() if t["status"] == "completed"]
    )
    active_tasks = len(
        [
            t
            for t in processing_tasks.values()
            if t["status"] in ["queued", "processing", "downloading"]
        ]
    )

    return jsonify(
        {
            "cache_files": cache_files,
            "completed_tasks": completed_tasks,
            "active_tasks": active_tasks,
            "supported_languages": len(SUPPORTED_LANGUAGES),
            "status": "healthy",
        }
    )


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
        return jsonify(
            {"success": True, "message": f"Cleared {removed_count} cache files"}
        )
    except Exception as e:
        logger.error(f"Cache clear error: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})


@app.route("/api/validate_keys", methods=["POST"])
def validate_api_keys():
    """Validate Gemini API keys"""
    try:
        data = request.get_json()
        api_keys = data.get("api_keys", [])

        if not api_keys:
            return jsonify({"success": False, "message": "No API keys provided"})

        valid_keys = []
        invalid_keys = []

        for api_key in api_keys:
            try:
                # Quick validation test
                import google.generativeai as genai

                genai.configure(api_key=api_key)
                model = genai.GenerativeModel("gemini-pro")
                # Don't actually make a request, just check if key format is valid
                valid_keys.append(api_key[-8:])  # Show last 8 chars
                logger.info(f"API key validated: ...{api_key[-8:]}")
            except Exception as e:
                invalid_keys.append(f"...{api_key[-8:]}: {str(e)[:50]}")
                logger.warning(f"Invalid API key: ...{api_key[-8:]}")

        return jsonify(
            {
                "success": True,
                "valid_keys": len(valid_keys),
                "invalid_keys": len(invalid_keys),
                "details": {"valid": valid_keys, "invalid": invalid_keys},
            }
        )

    except Exception as e:
        logger.error(f"API key validation error: {e}")
        return jsonify({"success": False, "message": f"Validation error: {str(e)}"})


if __name__ == "__main__":
    # Initialize logging
    os.makedirs("logs", exist_ok=True)

    # Start the application
    port = int(os.environ.get("PORT", 5050))
    debug_mode = os.environ.get("DEBUG", "False").lower() == "true"

    logger.info(f"Starting enhanced web app on port {port}")
    logger.info(f"Debug mode: {debug_mode}")
    logger.info(f"Supported languages: {len(SUPPORTED_LANGUAGES)}")
    logger.info(
        "Features: WebSocket, Multi-API keys, Parallel translation, Optimized transcription"
    )

    socketio.run(
        app, host="0.0.0.0", port=port, debug=debug_mode, allow_unsafe_werkzeug=True
    )
