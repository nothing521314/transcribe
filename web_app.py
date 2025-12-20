# web_app.py
from typing import List, Dict
import os
import hashlib
import eventlet
import pickle
from datetime import datetime
from pathlib import Path
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
)
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename
import time
import logging
import yt_dlp
import re

# Import enhanced modules
from video_subtitle_processor import OptimizedVideoSubtitleProcessor
from enhanced_translation_manager import EnhancedTranslationManager
from routes.enhance_subtitle import init_enhance_routes

# Ensure current directory is in Python path
from shared_state import (
    cancel_flags, 
    processing_tasks, 
    task_processors, 
    task_threads, 
    translation_managers
)

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
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
    always_connect=True,
    transports=['websocket', 'polling'],
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
    "english": {"code": "en", "name": "English", "native": "Tiếng Anh", "flag": "🇺🇸"},
    "chinese": {"code": "zh-cn", "name": "Chinese (Simplified)", "native": "Tiếng Trung (Giản thể)", "flag": "🇨🇳"},
    "chinese_traditional": {"code": "zh-tw", "name": "Chinese (Traditional)", "native": "Tiếng Trung (Phồn thể)", "flag": "🇹🇼"},
    "japanese": {"code": "ja", "name": "Japanese", "native": "Tiếng Nhật", "flag": "🇯🇵"},
    "korean": {"code": "ko", "name": "Korean", "native": "Tiếng Hàn", "flag": "🇰🇷"},
    "french": {"code": "fr", "name": "French", "native": "Tiếng Pháp", "flag": "🇫🇷"},
    "spanish": {"code": "es", "name": "Spanish", "native": "Tiếng Tây Ban Nha", "flag": "🇪🇸"},
    "german": {"code": "de", "name": "German", "native": "Tiếng Đức", "flag": "🇩🇪"},
    "italian": {"code": "it", "name": "Italian", "native": "Tiếng Ý", "flag": "🇮🇹"},
    "portuguese": {"code": "pt", "name": "Portuguese", "native": "Tiếng Bồ Đào Nha", "flag": "🇵🇹"},
    "russian": {"code": "ru", "name": "Russian", "native": "Tiếng Nga", "flag": "🇷🇺"},
    "arabic": {"code": "ar", "name": "Arabic", "native": "Tiếng Ả Rập", "flag": "🇸🇦"},
    "thai": {"code": "th", "name": "Thai", "native": "Tiếng Thái", "flag": "🇹🇭"},
    "hindi": {"code": "hi", "name": "Hindi", "native": "Tiếng Hindi", "flag": "🇮🇳"},
    "indonesian": {"code": "id", "name": "Indonesian", "native": "Tiếng Indonesia", "flag": "🇮🇩"},
    "malaysian": {"code": "ms", "name": "Malaysian", "native": "Tiếng Malaysia", "flag": "🇲🇾"},
    "dutch": {"code": "nl", "name": "Dutch", "native": "Tiếng Hà Lan", "flag": "🇳🇱"},
    "swedish": {"code": "sv", "name": "Swedish", "native": "Tiếng Thụy Điển", "flag": "🇸🇪"},
    "norwegian": {"code": "no", "name": "Norwegian", "native": "Tiếng Na Uy", "flag": "🇳🇴"},
    "danish": {"code": "da", "name": "Danish", "native": "Tiếng Đan Mạch", "flag": "🇩🇰"},
    "polish": {"code": "pl", "name": "Polish", "native": "Tiếng Ba Lan", "flag": "🇵🇱"},
    "czech": {"code": "cs", "name": "Czech", "native": "Tiếng Séc", "flag": "🇨🇿"},
    "hungarian": {"code": "hu", "name": "Hungarian", "native": "Tiếng Hungary", "flag": "🇭🇺"},
    "turkish": {"code": "tr", "name": "Turkish", "native": "Tiếng Thổ Nhĩ Kỳ", "flag": "🇹🇷"},
    "greek": {"code": "el", "name": "Greek", "native": "Tiếng Hy Lạp", "flag": "🇬🇷"},
    "hebrew": {"code": "he", "name": "Hebrew", "native": "Tiếng Do Thái", "flag": "🇮🇱"},
    "finnish": {"code": "fi", "name": "Finnish", "native": "Tiếng Phần Lan", "flag": "🇫🇮"},
    "ukrainian": {"code": "uk", "name": "Ukrainian", "native": "Tiếng Ukraina", "flag": "🇺🇦"},
    "bulgarian": {"code": "bg", "name": "Bulgarian", "native": "Tiếng Bulgaria", "flag": "🇧🇬"},
    "romanian": {"code": "ro", "name": "Romanian", "native": "Tiếng Rumani", "flag": "🇷🇴"},
    "croatian": {"code": "hr", "name": "Croatian", "native": "Tiếng Croatia", "flag": "🇭🇷"},
    "serbian": {"code": "sr", "name": "Serbian", "native": "Tiếng Serbia", "flag": "🇷🇸"},
    "slovenian": {"code": "sl", "name": "Slovenian", "native": "Tiếng Slovenia", "flag": "🇸🇮"},
    "slovak": {"code": "sk", "name": "Slovak", "native": "Tiếng Slovakia", "flag": "🇸🇰"},
    "lithuanian": {"code": "lt", "name": "Lithuanian", "native": "Tiếng Litva", "flag": "🇱🇹"},
    "latvian": {"code": "lv", "name": "Latvian", "native": "Tiếng Latvia", "flag": "🇱🇻"},
    "estonian": {"code": "et", "name": "Estonian", "native": "Tiếng Estonia", "flag": "🇪🇪"},
}

def cleanup_task(task_id, status = 'cancelled'):
    """Clean up resources for cancelled task"""
    try:
        # Clean up processor
        if task_id in task_processors:
            del task_processors[task_id]
            
        # Clean up thread reference
        if task_id in task_threads:
            del task_threads[task_id]
            
        # Clean up cancel flag
        if task_id in cancel_flags:
            del cancel_flags[task_id]
            
        # Update task status
        if task_id in processing_tasks:
            processing_tasks[task_id]["status"] = status
            processing_tasks[task_id]["end_time"] = datetime.now()
            
        logger.info(f"Cleaned up cancelled task: {task_id}")
        
    except Exception as e:
        logger.error(f"Error cleaning up task {task_id}: {e}")

init_enhance_routes(app, socketio, OUTPUT_FOLDER, cleanup_task)

def heartbeat(task_id):
    """Optimized heartbeat với flush"""
    while processing_tasks.get(task_id, {}).get("status") == "processing":
        if cancel_flags.get(task_id):
            break
        try:
            socketio.emit("keep_alive", {"task_id": task_id}, room=task_id)
            socketio.sleep(0)
        except:
            break
        socketio.sleep(20)
        
def check_cancellation(task_id):
    """Check if task should be cancelled and raise if so"""
    if cancel_flags.get(task_id):
        logger.info(f"Task {task_id} cancellation detected")
        raise InterruptedError(f"Task {task_id} was cancelled")

def emit_with_cancel_check(task_id, *args, **kwargs):
    """Emit progress and check for cancellation"""
    check_cancellation(task_id)
    socketio.emit(*args, **kwargs)
    socketio.sleep(0)
    check_cancellation(task_id)

class CancellableWhisperModel:
    """Wrapper cho Whisper model với khả năng cancel sử dụng eventlet"""
    
    def __init__(self, model, task_id):
        self.model = model
        self.task_id = task_id
        self.socketio = socketio
        self.last_progress_time = 0
        self.start_time = None
        
    def transcribe(self, *args, **kwargs):
        """Transcribe với progress tracking dựa trên timeline"""
        if cancel_flags.get(self.task_id):
            raise InterruptedError("Task was cancelled before transcription")
            
        self.start_time = time.time()
        
        # Lấy audio path và duration
        audio_path = args[0] if args else kwargs.get('audio')
        total_duration = self._get_audio_duration(audio_path)
        
        try:
            # faster-whisper trả về (segments_generator, info)
            segments_gen, info = self.model.transcribe(*args, **kwargs)
            
            segments = []
            last_emit_time = time.time()
            last_progress = 0
            
            # Iterate qua generator để track progress theo timeline
            for segment in segments_gen:
                # Check cancellation
                if cancel_flags.get(self.task_id):
                    logger.info(f"Transcription cancelled at segment {len(segments)}")
                    raise InterruptedError("Task was cancelled during transcription")
                
                # faster-whisper segment có attributes: start, end, text
                segments.append({
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text,
                    'words': segment.words if hasattr(segment, 'words') else None
                })
                
                current_time = time.time()
                
                # Tính progress dựa trên timeline
                if total_duration > 0:
                    # Sử dụng end time của segment hiện tại làm progress
                    timeline_progress = min((segment.end / total_duration) * 95, 95)
                else:
                    # Fallback: dựa trên info.duration nếu có
                    if hasattr(info, 'duration') and info.duration > 0:
                        timeline_progress = min((segment.end / info.duration) * 95, 95)
                    else:
                        # Last resort: time-based estimate
                        elapsed = current_time - self.start_time
                        timeline_progress = min((elapsed / 60) * 90, 90)
                
                # Emit có điều kiện thông minh
                should_emit = (
                    len(segments) == 1 or  # First segment
                    timeline_progress >= last_progress + 5 or  # Every 5% progress
                    current_time - last_emit_time >= 3 or  # Every 3 seconds minimum
                    timeline_progress >= 90  # Near completion
                )
                
                if should_emit:
                    self.emit_transcription_progress_timeline(
                        timeline_progress, 
                        current_time=segment.end,
                        total_duration=total_duration or (info.duration if hasattr(info, 'duration') else 0),
                        segment_count=len(segments)
                    )
                    last_emit_time = current_time
                    last_progress = timeline_progress
                
                # Yield control
                eventlet.sleep(0)
            
            # Final progress
            final_duration = info.duration if hasattr(info, 'duration') else total_duration
            self.emit_transcription_progress_timeline(
                100, 
                current_time=final_duration,
                total_duration=final_duration,
                segment_count=len(segments)
            )
            
            # Return compatible format
            result = {
                'segments': segments,
                'language': info.language,
                'language_probability': info.language_probability,
                'duration': info.duration,
            }
            
            logger.info(f"Transcription completed: {len(segments)} segments, {info.duration:.1f}s duration")
            return result
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            raise

    def _get_audio_duration(self, audio_path: str) -> float:
        """Lấy duration của audio/video file"""
        try:
            import subprocess
            import json
            
            # Sử dụng ffprobe để lấy duration chính xác
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', audio_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data['format']['duration'])
                logger.info(f"Audio duration: {duration:.1f}s")
                return duration
            else:
                logger.warning(f"ffprobe failed: {result.stderr}")
                
        except Exception as e:
            logger.warning(f"Could not get audio duration: {e}")
        
        # Fallback: estimate từ file size (rough)
        try:
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            # Very rough estimate: 1MB ≈ 10-15 seconds for compressed video
            estimated_duration = file_size_mb * 12
            logger.info(f"Estimated duration: {estimated_duration:.1f}s from file size")
            return estimated_duration
        except:
            return 0

    def emit_transcription_progress_timeline(self, progress, current_time=0, total_duration=0, segment_count=0):
        """Emit progress với timeline information"""
        current_timestamp = time.time()
        elapsed = current_timestamp - self.start_time if self.start_time else 0
        
        if self.socketio and self.task_id:
            try:
                progress = round(progress, 1)
                
                # Tạo message với timeline info
                if total_duration > 0 and current_time > 0:
                    time_str = f"{current_time:.1f}s/{total_duration:.1f}s"
                    message = f"Transcribing... {progress:.0f}% ({time_str}, {segment_count} segments)"
                elif segment_count > 0:
                    message = f"Transcribing... {progress:.0f}% ({segment_count} segments)"
                else:
                    message = f"Transcribing... {progress:.0f}%"
                
                data = {
                    "task_id": self.task_id,
                    "step": "transcription", 
                    "step_progress": min(progress, 100),
                    "overall_progress": 20 + (min(progress, 100) * 0.4),
                    "message": message,
                    "status": "processing",
                    "elapsed_time": round(elapsed, 1),
                    "timeline_position": round(current_time, 1),
                    "total_duration": round(total_duration, 1),
                    "segment_count": segment_count,
                }
                
                # Emit với aggressive flushing
                self.socketio.emit("progress_update", data, room=self.task_id)
                eventlet.sleep(0)
                eventlet.sleep(0)
                
                # Log ít hơn để tránh spam
                if progress % 10 == 0 or progress >= 100 or segment_count <= 3:
                    logger.info(f"[TRANSCRIPTION] {self.task_id}: {progress:.0f}% at {current_time:.1f}s/{total_duration:.1f}s")
                
            except Exception as e:
                logger.error(f"Failed to emit timeline progress: {e}")

def handle_merge_lines(segments: List[Dict]) -> List[Dict]:
        """Merge consecutive subtitle lines (pairwise: 0+1, 2+3, ...)"""
        merged = []

        for i in range(0, len(segments), 2):
            if i + 1 < len(segments):
                seg1 = segments[i]
                seg2 = segments[i + 1]
                merged.append(
                    {
                        "start": seg1["start"],
                        "end": seg2["end"],
                        "text": f"{seg1['text']} {seg2['text']}".strip(),
                    }
                )
            else:
                # Last segment (odd count) - keep as-is
                merged.append(segments[i])

        logger.info(f"Merged {len(segments)} segments into {len(merged)}")
        return merged
    
class EnhancedOptimizedVideoSubtitleProcessor(OptimizedVideoSubtitleProcessor):
    """Enhanced processor with intelligent API management and WebSocket integration"""

    def __init__(self, model_size="base", gemini_api_keys=None, socketio=None, task_id=None):
        super().__init__(model_size, gemini_api_keys, socketio)
        
        self.task_id = task_id
        self.is_cancelled = False
        
        # Wrap model với cancellation support
        if hasattr(self, 'model') and task_id:
            self.model = CancellableWhisperModel(self.model, task_id)
        
        logger.info(f"Initialized enhanced processor with cancellation support for task {task_id}")
        
        # Enhanced logging for web app
        logger.info(f"🌐 Initialized enhanced web processor")
        logger.info(f"🔑 API Management: {len(gemini_api_keys or [])} keys")

    def check_cancellation(self):
        """Check if task should be cancelled"""
        if self.task_id and cancel_flags.get(self.task_id):
            self.is_cancelled = True
            raise InterruptedError(f"Task {self.task_id} was cancelled")

    def emit_translation_status(self, language: str, status: str, message: str, progress: int = None):
        """Emit translation status updates"""
        self.check_cancellation()
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
        if task_id and cancel_flags.get(task_id):
            raise InterruptedError("Task was cancelled before translation")
        if task_id:
            self.set_task_id(task_id)
        
        results = {}
        results_lock = eventlet.semaphore.Semaphore()
        pool = eventlet.GreenPool(size=min(3, len(target_languages)))
        
        def run_translation(language: str):
            try:
                if task_id and cancel_flags.get(task_id):
                    logger.info(f"Translation cancelled before starting {language}")
                    with results_lock:
                        results[language] = []
                    return
                self.translation_manager.set_task_id(task_id)
                self.emit_translation_status(language, 'starting', f'Starting {language} translation...')
                translations = self.translation_manager.translate_texts(texts, language)

                if task_id and cancel_flags.get(task_id):
                    logger.info(f"Translation for {language} completed but task was cancelled")
                    with results_lock:
                        results[language] = []
                    return

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
                    
            except InterruptedError:
                logger.info(f"Translation interrupted for {language}")
                with results_lock:
                    results[language] = []
            except Exception as e:
                self.emit_translation_status(language, 'error', f'{language} failed: {e}')
                with results_lock:
                    results[language] = texts

        for lang in target_languages:
            if task_id and cancel_flags.get(task_id):
                logger.info("Stopping translation launch due to cancellation")
                break
            pool.spawn(run_translation, lang)

        try:
            pool.waitall()
        except InterruptedError:
            logger.info("Parallel translation cancelled")
            raise

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
        if cancel_flags.get(task_id):
            raise InterruptedError("Download cancelled")
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
                    room=task_id
                )
                socketio.sleep(0)
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
            if cancel_flags.get(task_id):
                raise InterruptedError("Download cancelled")
            info = ydl.extract_info(url, download=True)

            if info:
                filename = ydl.prepare_filename(info)
                logger.info(f"Download completed: {filename}")
                return filename, info.get("title", "Unknown")
    except InterruptedError:
        logger.info(f"Download cancelled for task {task_id}")
        raise
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
    global processing_tasks, task_processors

    try:
        logger.info(f"Starting enhanced processing for task {task_id}")
        start_time = time.time()

        processing_tasks[task_id]["status"] = "processing"
        processing_tasks[task_id]["start_time"] = datetime.now()

        def emit_step_progress(step_id, step_progress, message, force_emit=False, **kwargs):
            """Enhanced emit function with better reliability"""
            check_cancellation(task_id)
            if cancel_flags.get(task_id):
                raise InterruptedError("Task cancelled")

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
                socketio.sleep(0)
                check_cancellation(task_id)
                processing_tasks[task_id]["message"] = message
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
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled during initialization")

        emit_step_progress("initialization", 0, "Initializing enhanced processor...")
        socketio.sleep(0)
        
        processor = EnhancedOptimizedVideoSubtitleProcessor(
            model_size=options.get("model_size", "base"), 
            gemini_api_keys=api_keys,
            socketio=socketio,
            task_id=task_id
        )
        processor.set_task_id(task_id)
        
        task_processors[task_id] = processor
        
        emit_step_progress("initialization", 100, "Enhanced processor initialized")
        socketio.sleep(0)

        # Step 2: Handle video input
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled before download")

        if not video_path and processing_tasks[task_id].get("video_url"):
            video_url = processing_tasks[task_id]["video_url"]
            emit_step_progress("download", 0, "Starting video download...")

            output_dir = os.path.join(UPLOAD_FOLDER, 'videos')
            downloaded_path, title = download_youtube_video(
                video_url, output_dir, task_id
            )
            if not downloaded_path:
                raise RuntimeError(f"Cannot download video: {title}")

            video_path = downloaded_path
            processing_tasks[task_id]["video_path"] = video_path
            processing_tasks[task_id]["original_filename"] = title
            emit_step_progress("download", 100, "Download completed")
        else:
            emit_step_progress("download", 100, "Using uploaded file")
            
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled after download")

        file_hash = get_file_hash(video_path)
        cached_transcription = load_from_cache(file_hash, "transcription")
        
        # Validate cache has words info (required for sentence splitting)
        if cached_transcription and 'segments' in cached_transcription:
            has_words = False
            for seg in cached_transcription['segments'][:5]: # Check first few segments
                if seg.get('words'):
                    has_words = True
                    break
            if not has_words:
                logger.warning("⚠️ Cached transcription missing word timestamps. Re-transcribing...")
                cached_transcription = None

        socketio.sleep(0)

        # Step 3: Transcription
        if cached_transcription:
            emit_step_progress("transcription", 0, "Found cached transcription...")
            result = cached_transcription
            emit_step_progress("transcription", 100, "Using cached transcription data")
            socketio.sleep(0)
        else:
            if cancel_flags.get(task_id):
                raise InterruptedError("Task cancelled before transcription")

            emit_step_progress("transcription", 0, "Starting audio transcription...")
            socketio.sleep(0)

            # Set start time cho progress estimation
            processor.model._start_time = time.time()
            
            result = processor.model.transcribe(
                video_path,
                word_timestamps=True,
                language="en",
                temperature=0,
                best_of=3,
                beam_size=3,
                patience=1.0,
            )
            logger.info(f"Đã nhận dạng được {len(result['segments'])} segments")

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
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled before timing optimization")

        emit_step_progress("timing", 0, "Starting timing optimization...")
        socketio.sleep(0)
        
        improved_segments = processor.improve_subtitle_timing(
            result["segments"],
            max_chars_per_line=options.get("max_chars", 50),
            max_duration=options.get("max_duration", 6.0),
        )
        
        # Merge segments
        if options.get("merge_lines", False):
            improved_segments = handle_merge_lines(improved_segments)
            emit_step_progress("merging", 100, f"Merged {improved_segments} segments")
            socketio.sleep(0)

        emit_step_progress("timing", 50, f"Optimized {len(improved_segments)} segments")
        socketio.sleep(0)
        
        # Create original SRT
        base_name = Path(video_path).stem
        srt_path = os.path.join(OUTPUT_FOLDER, "srt")
        original_srt_path = os.path.join(srt_path, f"{base_name}_original.srt")
        processor.create_srt_from_segments(improved_segments, original_srt_path)
        
        emit_step_progress("timing", 100, "Original SRT file created")
        socketio.sleep(0)

        # Step 5: Enhanced Translation
        translated_files = {}
        if target_languages and api_keys:
            if cancel_flags.get(task_id):
                raise InterruptedError("Task cancelled before translation")

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
                    if cancel_flags.get(task_id):
                        raise InterruptedError("Task cancelled during file creation")

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

                        translate_dir = os.path.join(OUTPUT_FOLDER, "translations")
                        lang_srt_path = os.path.join(translate_dir, f"{base_name}_{lang}.srt")
                        processor.create_srt_from_segments(translated_segments, lang_srt_path)
                        translated_files[lang] = lang_srt_path

                emit_step_progress("translation", 100, "All translations completed")
                socketio.sleep(0)

            except InterruptedError:
                logger.info(f"Translation cancelled for task {task_id}")
                raise
            except Exception as translation_error:
                    logger.error(f"Translation error: {translation_error}")
                    emit_step_progress("translation", 100, f"Translation completed with errors: {str(translation_error)}")
                    socketio.sleep(0.5)
        else:
            # Skip translation
            emit_step_progress("translation", 100, "Translation skipped - no API keys provided")
            socketio.sleep(0)

        # Step 6: Completion
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled before completion")

        logger.info("Starting completion phase...")
        socketio.sleep(0.2)  # Small delay before completion
        emit_step_progress("completion", 0, "Finalizing results...")
        socketio.sleep(0)

        # Prepare results for frontend
        files_for_download = []
        files_for_download.append({
            "filename": os.path.basename(original_srt_path),
            "name": "Bản gốc (English)",
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
        socketio.sleep(0.5)
        logger.info(f"Task {task_id} completed successfully with enhanced translation")
        # Log final API status
        api_status = processor.get_api_status()
        logger.info(f"📊 Final API Status - Gemini: {api_status['total_usage']} requests, "
                   f"{api_status['total_errors']} errors, Google Translate: {api_status['google_translate']}")

    except InterruptedError as e:
        logger.info(f"Task {task_id} was cancelled: {e}")
        cleanup_task(task_id)
        
        # Emit cancellation notification
        try:
            socketio.emit("task_cancelled", {
                "task_id": task_id,
                "message": "Task was cancelled by user",
                "status": "cancelled"
            }, room=task_id)
            socketio.sleep(0.1)
        except:
            pass
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
    finally:
        # Always clean up resources
        cleanup_task(task_id, 'completed')

def parse_srt_to_segments(srt_path: str) -> List[Dict]:
    """
    Parse SRT file to segments format compatible with video processor.
    
    Args:
        srt_path: Path to SRT file
        
    Returns:
        List of segment dictionaries with 'start', 'end', 'text' keys
    """
    segments = []
    
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        
        # Split by double newlines to get individual subtitle blocks
        blocks = re.split(r'\n\s*\n', content)
        
        for block in blocks:
            if not block.strip():
                continue
                
            lines = block.strip().split('\n')
            
            # Skip if block doesn't have at least 3 lines (index, timestamp, text)
            if len(lines) < 3:
                continue
            
            # Line 0: subtitle index (skip)
            # Line 1: timestamp
            timestamp_line = lines[1]
            
            # Parse timestamp: "00:00:00,000 --> 00:00:01,760"
            timestamp_match = re.match(
                r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})',
                timestamp_line
            )
            
            if not timestamp_match:
                logger.warning(f"Invalid timestamp format: {timestamp_line}")
                continue
            
            # Extract start time
            start_h, start_m, start_s, start_ms = map(int, timestamp_match.groups()[:4])
            start_time = start_h * 3600 + start_m * 60 + start_s + start_ms / 1000
            
            # Extract end time
            end_h, end_m, end_s, end_ms = map(int, timestamp_match.groups()[4:])
            end_time = end_h * 3600 + end_m * 60 + end_s + end_ms / 1000
            
            # Lines 2+: subtitle text (may span multiple lines)
            text = '\n'.join(lines[2:]).strip()
            
            if text:  # Only add if there's actual text
                segments.append({
                    'start': start_time,
                    'end': end_time,
                    'text': text
                })
        
        logger.info(f"Parsed {len(segments)} segments from SRT file: {srt_path}")
        return segments
        
    except FileNotFoundError:
        logger.error(f"SRT file not found: {srt_path}")
        return []
    except Exception as e:
        logger.error(f"Error parsing SRT file {srt_path}: {e}")
        return []

def process_srt_task_enhanced(
    task_id, srt_path, target_languages, api_keys, options
):
    """Enhanced SRT processing starting from step 3 (timing optimization)"""
    global processing_tasks, task_processors

    try:
        logger.info(f"Starting enhanced SRT processing for task {task_id}")
        start_time = time.time()

        processing_tasks[task_id]["status"] = "processing"
        processing_tasks[task_id]["start_time"] = datetime.now()

        def emit_step_progress(step_id, step_progress, message, force_emit=False, **kwargs):
            """Enhanced emit function with better reliability"""
            check_cancellation(task_id)
            if cancel_flags.get(task_id):
                raise InterruptedError("Task cancelled")

            # Adjusted weights for SRT processing (no download/transcription)
            step_weights = {
                "initialization": 10,
                "loading": 15,
                "timing": 25,
                "translation": 45,
                "completion": 5,
            }

            step_starts = {
                "initialization": 0,
                "loading": 10,
                "timing": 25,
                "translation": 50,
                "completion": 95,
            }

            base_progress = step_starts.get(step_id, 0)
            step_weight = step_weights.get(step_id, 5)
            overall_progress = base_progress + (step_progress * step_weight / 100)
            overall_progress = min(max(overall_progress, 0), 100)

            elapsed_time = time.time() - start_time

            # Estimate remaining time
            if overall_progress > 5:
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
                socketio.emit("progress_update", progress_data, room=task_id)
                socketio.sleep(0)
                check_cancellation(task_id)
                processing_tasks[task_id]["message"] = message
                logger.info(f"[{task_id}] {step_id} {step_progress}% - {message}")
                
                if force_emit or step_progress >= 100:
                    socketio.sleep(0.1)
                else:
                    socketio.sleep(0)
                    
            except Exception as e:
                logger.error(f"Failed to emit progress for {task_id}: {e}")

        # Step 1: Initialization
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled during initialization")

        emit_step_progress("initialization", 0, "Initializing SRT processor...")
        socketio.sleep(0)
        
        processor = EnhancedOptimizedVideoSubtitleProcessor(
            model_size=options.get("model_size", "base"), 
            gemini_api_keys=api_keys,
            socketio=socketio,
            task_id=task_id
        )
        processor.set_task_id(task_id)
        task_processors[task_id] = processor
        
        emit_step_progress("initialization", 100, "Processor initialized")
        socketio.sleep(0)

        # Step 2: Load SRT file
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled before loading SRT")

        emit_step_progress("download", 0, "Loading SRT file...")
        socketio.sleep(0)

        # Parse SRT file to segments
        segments = parse_srt_to_segments(srt_path)
        if not segments:
            raise RuntimeError("Failed to parse SRT file or file is empty")

        emit_step_progress("download", 100, f"Loaded {len(segments)} segments from SRT")
        socketio.sleep(0)

        emit_step_progress("transcription", 100, f"Skipping transcription")
        socketio.sleep(0)

        # Step 3: Timing optimization
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled before timing optimization")

        emit_step_progress("timing", 0, "Starting timing optimization...")
        socketio.sleep(0)
        
        improved_segments = processor.improve_subtitle_timing(
            segments,
            max_chars_per_line=options.get("max_chars", 50),
            max_duration=options.get("max_duration", 6.0),
        )

        if options.get("merge_lines", False):
            improved_segments = handle_merge_lines(improved_segments)
            emit_step_progress("merging", 100, f"Merged {len(improved_segments)} segments")
            socketio.sleep(0)

        emit_step_progress("timing", 50, f"Optimized {len(improved_segments)} segments")
        socketio.sleep(0)
        
        # Create optimized original SRT
        base_name = Path(srt_path).stem
        srt_output_dir = os.path.join(OUTPUT_FOLDER, "srt")
        os.makedirs(srt_output_dir, exist_ok=True)
        original_srt_path = os.path.join(srt_output_dir, f"{base_name}_optimized.srt")
        processor.create_srt_from_segments(improved_segments, original_srt_path)
        
        emit_step_progress("timing", 100, "Optimized SRT file created")
        socketio.sleep(0)

        # Step 4: Enhanced Translation
        translated_files = {}
        if target_languages and api_keys:
            if cancel_flags.get(task_id):
                raise InterruptedError("Task cancelled before translation")

            emit_step_progress(
                "translation", 0, f"Starting translation to {len(target_languages)} languages..."
            )
            socketio.sleep(0)

            texts = [s["text"] for s in improved_segments]
            try:
                translated_texts_dict = processor.enhanced_parallel_translate(
                    texts, target_languages, task_id
                )
                
                total_langs = len(translated_texts_dict)
                processed_langs = 0

                # Create translated SRT files
                translate_dir = os.path.join(OUTPUT_FOLDER, "translations")
                os.makedirs(translate_dir, exist_ok=True)
                
                for lang, translated_texts in translated_texts_dict.items():
                    if cancel_flags.get(task_id):
                        raise InterruptedError("Task cancelled during file creation")

                    processed_langs += 1
                    file_progress = 85 + (processed_langs * 15 // total_langs)
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

                        lang_srt_path = os.path.join(translate_dir, f"{base_name}_{lang}.srt")
                        processor.create_srt_from_segments(translated_segments, lang_srt_path)
                        translated_files[lang] = lang_srt_path

                emit_step_progress("translation", 100, "All translations completed")
                socketio.sleep(0)

            except InterruptedError:
                logger.info(f"Translation cancelled for task {task_id}")
                raise
            except Exception as translation_error:
                logger.error(f"Translation error: {translation_error}")
                emit_step_progress("translation", 100, f"Translation completed with errors: {str(translation_error)}")
                socketio.sleep(0.5)
        else:
            emit_step_progress("translation", 100, "Translation skipped - no API keys provided")
            socketio.sleep(0)

        # Step 5: Completion
        if cancel_flags.get(task_id):
            raise InterruptedError("Task cancelled before completion")

        logger.info("Starting completion phase...")
        socketio.sleep(0.2)
        emit_step_progress("completion", 0, "Finalizing results...")
        socketio.sleep(0)

        # Prepare results for frontend
        files_for_download = []
        files_for_download.append({
            "filename": os.path.basename(original_srt_path),
            "name": "Bản gốc (Optimized)",
            "flag": "✨",
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
            "files": files_for_download,
            "total_time": time.time() - start_time,
            "api_status": processor.get_api_status()
        }

        emit_step_progress("completion", 90, "Saving task results...")
        socketio.sleep(0)

        # Final completion
        total_time = time.time() - start_time
        emit_step_progress("completion", 100, f"All tasks completed in {total_time:.1f}s!")
        socketio.sleep(0.5)

        completion_data = {
            "task_id": task_id,
            "results": {
                "segments_count": len(improved_segments),
                "files": files_for_download,
                "total_time": total_time,
                "api_status": processor.get_api_status()
            },
        }

        socketio.emit("task_completed", completion_data, room=task_id)
        socketio.sleep(0.5)
        logger.info(f"SRT task {task_id} completed successfully")

    except InterruptedError as e:
        logger.info(f"Task {task_id} was cancelled: {e}")
        cleanup_task(task_id)
        
        try:
            socketio.emit("task_cancelled", {
                "task_id": task_id,
                "message": "Task was cancelled by user",
                "status": "cancelled"
            }, room=task_id)
            socketio.sleep(0.1)
        except:
            pass
            
    except Exception as e:
        logger.error(f"SRT processing error for task {task_id}: {e}")
        processing_tasks[task_id]["status"] = "error"

        error_data = {
            "task_id": task_id,
            "step": "error",
            "overall_progress": 0,
            "message": f"Error: {str(e)}",
            "status": "error",
        }

        socketio.emit("progress_update", error_data, room=task_id)
    finally:
        cleanup_task(task_id, 'completed')

# Enhanced WebSocket event handlers
@socketio.on("connect")
def handle_connect():
    logger.info(f"✅ Client connected: {request.sid}")
    emit("connected", {"data": "Connected to Enhanced AI Subtitle Generator", "sid": request.sid})


@socketio.on("disconnect")
def handle_disconnect():
    logger.info(f"❌ Client disconnected: {request.sid}")


@socketio.on("join_task")
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

        # SEND CURRENT STATUS IMMEDIATELY
        if task_id in processing_tasks:
            task = processing_tasks[task_id]
            
            # Send buffered progress if available
            if "last_progress" in task:
                logger.info(f"Sending buffered progress to newly joined client: {task['last_progress']}")
                emit("enhance_progress", task["last_progress"], room=request.sid)
                eventlet.sleep(0)
            
            # Send task status
            emit("task_status", {
                "task_id": task_id,
                "status": task["status"],
                "message": task.get("message", f'Current task status: {task["status"]}'),
            }, room=request.sid)
            eventlet.sleep(0)


@socketio.on("leave_task")
def handle_leave_task(data):
    task_id = data.get("task_id")
    if task_id:
        leave_room(task_id)
        logger.info(f"🚪 Client {request.sid} left task room: {task_id}")

@socketio.on("cancel_task")
def handle_cancel_task(data):
    """Handle task cancellation from WebSocket"""
    task_id = data.get("task_id")
    if not task_id:
        emit("error", {"message": "Task ID required"}, room=request.sid)
        return
        
    logger.info(f"Received cancel request for task {task_id} from {request.sid}")
    
    if task_id not in processing_tasks:
        emit("error", {"message": "Task not found"}, room=request.sid)
        return
    
    current_status = processing_tasks[task_id]["status"]
    
    # ALLOW CANCEL EVEN IF ALREADY CANCELLING (in case first attempt didn't work)
    if current_status not in ["queued", "processing", "cancelling"]:  # Add "cancelling" here
        emit("cancel_result", {
            "task_id": task_id,
            "success": False,
            "message": f"Cannot cancel task with status: {current_status}"
        }, room=request.sid)
        return
    
    # Set cancel flag
    cancel_flags[task_id] = True
    
    # Update task status
    processing_tasks[task_id]["status"] = "cancelling"
    processing_tasks[task_id]["cancel_time"] = datetime.now()
    
    # Emit acknowledgment
    emit("cancel_acknowledged", {
        "task_id": task_id,
        "message": "Cancellation request received, stopping task...",
        "status": "cancelling"
    }, room=task_id)
    
    logger.info(f"Task {task_id} marked for cancellation (was {current_status})")


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
            "merge_lines": request.form.get("merge_lines", "false").lower() == "true",
        }

        video_path = None
        audio_path = None
        srt_path = None
        original_filename = None
        video_url = None
        file_type = None
        
        if "file" in request.files and request.files["file"].filename:
            file = request.files["file"]
            
            if file:
                filename = secure_filename(file.filename)
                file_ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
                
                # Check if it's an SRT file
                if file_ext == "srt":
                    output_dir = os.path.join(UPLOAD_FOLDER, "srt")
                    os.makedirs(output_dir, exist_ok=True)
                    srt_path = os.path.join(output_dir, filename)
                    file.save(srt_path)
                    original_filename = file.filename
                    file_type = "srt"
                    logger.info(f"SRT file uploaded: {srt_path}")
                    
                # Check if it's an audio file
                elif allowed_file(filename, "audio"):
                    output_dir = os.path.join(UPLOAD_FOLDER, "audio")
                    os.makedirs(output_dir, exist_ok=True)
                    audio_path = os.path.join(output_dir, filename)
                    file.save(audio_path)
                    original_filename = file.filename
                    file_type = "audio"
                    logger.info(f"Audio file uploaded: {audio_path}")
                    
                # Check if it's a video file
                elif allowed_file(filename, "video"):
                    output_dir = os.path.join(UPLOAD_FOLDER, "videos")
                    os.makedirs(output_dir, exist_ok=True)
                    video_path = os.path.join(output_dir, filename)
                    file.save(video_path)
                    original_filename = file.filename
                    file_type = "video"
                    logger.info(f"Video file uploaded: {video_path}")
                else:
                    return jsonify({
                        "success": False,
                        "message": "Invalid file type. Please upload a video, audio, or SRT file",
                    })

        elif request.form.get("video_url"):
            video_url = request.form.get("video_url")
            file_type = "url"
            logger.info(f"Received URL for enhanced processing: {video_url}")

        if not video_path and not audio_path and not video_url and not srt_path:
            return jsonify({
                "success": False,
                "message": "Please select a video/audio file or provide a URL",
            })

        # Initialize task with enhanced features
        processing_tasks[task_id] = {
            "status": "queued",
            "start_time": datetime.now(),
            "video_path": video_path or audio_path,  # Use audio_path if no video
            "audio_path": audio_path,
            "srt_path": srt_path,
            "file_type": file_type,
            "original_filename": original_filename,
            "video_url": video_url,
            "target_languages": target_languages,
            "api_keys": api_keys,
            "options": options,
        }
        
        # Initialize cancel flag
        cancel_flags[task_id] = False

        # Start enhanced processing
        socketio.start_background_task(heartbeat, task_id)
        
        if file_type == "srt":
            # Process SRT directly (skip transcription)
            processing_thread = socketio.start_background_task(
                process_srt_task_enhanced,
                task_id, srt_path, target_languages, api_keys, options
            )
        else:
            # Process video or audio normally
            # For audio files, use audio_path; for video use video_path
            media_path = audio_path if audio_path else video_path
            processing_thread = socketio.start_background_task(
                process_video_task_enhanced,
                task_id, media_path, target_languages, api_keys, options
            )
        
        # Store thread reference
        task_threads[task_id] = processing_thread

        logger.info(f"Started enhanced processing task {task_id} for {file_type}")

        return jsonify({
            "success": True, 
            "task_id": task_id,
            "file_type": file_type,
            "message": f"Enhanced processing started for {file_type} with intelligent API management"
        })

    except Exception as e:
        logger.error(f"Enhanced upload error: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route("/api/cancel_task/<task_id>", methods=["POST"])
def cancel_task_api(task_id):
    """API endpoint to cancel a specific task"""
    try:
        if task_id not in processing_tasks:
            return jsonify({
                "success": False,
                "message": "Task not found"
            }), 404

        current_status = processing_tasks[task_id]["status"]
        
        if current_status not in ["queued", "processing", "downloading"]:
            return jsonify({
                "success": False,
                "message": f"Cannot cancel task with status: {current_status}"
            }), 400

        # Set cancel flag
        cancel_flags[task_id] = True
        
        # Update status
        processing_tasks[task_id]["status"] = "cancelling"
        processing_tasks[task_id]["cancel_time"] = datetime.now()
        
        # Emit cancellation via WebSocket
        try:
            socketio.emit("cancel_acknowledged", {
                "task_id": task_id,
                "message": "Cancellation request received, stopping task...",
                "status": "cancelling"
            }, room=task_id)
        except:
            pass

        logger.info(f"API cancellation request for task {task_id}")
        
        return jsonify({
            "success": True,
            "message": f"Cancellation request sent for task {task_id}",
            "task_id": task_id
        })

    except Exception as e:
        logger.error(f"Cancel task API error: {e}")
        return jsonify({
            "success": False,
            "message": f"Error cancelling task: {str(e)}"
        }), 500

@app.route("/api/cancel_all_tasks", methods=["POST"])
def cancel_all_tasks():
    """API endpoint to cancel all active tasks"""
    try:
        cancelled_tasks = []
        
        for task_id, task in processing_tasks.items():
            if task["status"] in ["queued", "processing"]:
                # Set cancel flag
                cancel_flags[task_id] = True
                
                # Update status
                task["status"] = "cancelling"
                task["cancel_time"] = datetime.now()
                
                cancelled_tasks.append(task_id)
                
                # Emit cancellation via WebSocket
                try:
                    socketio.emit("cancel_acknowledged", {
                        "task_id": task_id,
                        "message": "Mass cancellation request received, stopping task...",
                        "status": "cancelling"
                    }, room=task_id)
                except:
                    pass

        logger.info(f"Mass cancellation requested for {len(cancelled_tasks)} tasks")
        
        return jsonify({
            "success": True,
            "message": f"Cancellation request sent for {len(cancelled_tasks)} tasks",
            "cancelled_tasks": cancelled_tasks
        })

    except Exception as e:
        logger.error(f"Cancel all tasks error: {e}")
        return jsonify({
            "success": False,
            "message": f"Error cancelling tasks: {str(e)}"
        }), 500

@app.route("/api/task_cancel_status/<task_id>")
def get_cancel_status(task_id):
    """Debug endpoint to check cancel status"""
    return jsonify({
        "task_id": task_id,
        "cancel_flag": cancel_flags.get(task_id, False),
        "task_exists": task_id in processing_tasks,
        "task_status": processing_tasks.get(task_id, {}).get("status", "unknown")
    })

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
    """Get enhanced task status including cancellation info"""
    if task_id not in processing_tasks:
        return jsonify({"error": "Task not found"}), 404

    task = processing_tasks[task_id]
    status_data = {
        "task_id": task_id,
        "status": task["status"],
        "start_time": task["start_time"].isoformat(),
        "cancellable": task["status"] in ["queued", "processing"],
        "is_cancelled": cancel_flags.get(task_id, False)
    }

    if task["status"] == "completed" and "results" in task:
        status_data["results"] = task["results"]
    elif task["status"] == "processing":
        elapsed_time = (datetime.now() - task["start_time"]).total_seconds()
        status_data["elapsed_time"] = elapsed_time
    elif task["status"] == "cancelled" and "cancel_time" in task:
        status_data["cancel_time"] = task["cancel_time"].isoformat()

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
        translation_manager = EnhancedTranslationManager(api_keys, socketio)
        
        # Test each key with a simple request
        valid_keys = []
        invalid_keys = []

        for i, key in enumerate(api_keys):
            try:
                # Quick validation
                import google.generativeai as genai
                genai.configure(api_key=key)
                model = genai.GenerativeModel("gemini-2.5-flash")
                
                # Small test request
                response = model.generate_content("Hello")
                
                if _extract_response_text(response):
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

def _extract_response_text(response) -> str:
        """
        Safely extract text from Gemini response (multi-part supported).
        """
        try:
            finish_reason = getattr(getattr(response, "candidates", [None])[0], "finish_reason", None)
            if finish_reason:
                logger.debug(f"Response finish reason: {finish_reason}")
                
            if finish_reason and finish_reason.value in [2, 3]: # STOP (2) hoặc SAFETY (3)
                logger.warning(f"Gemini finished with reason {finish_reason.value}. Checking prompt_feedback...")
                
                # Kiểm tra phản hồi bị chặn
                if hasattr(response, "prompt_feedback") and hasattr(response.prompt_feedback, "block_reason"):
                    logger.warning(f"Response blocked: {getattr(response.prompt_feedback.block_reason, 'name', 'N/A')}")
                return ""


            # Logic trích xuất chính: CHỈ lặp qua candidates/parts
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                content = getattr(candidate, "content", None)
                
                if content and hasattr(content, "parts"):
                    text_parts = []
                    for part in content.parts:
                        # Dùng getattr an toàn để trích xuất text
                        text = getattr(part, "text", "") 
                        if text:
                            text_parts.append(text)
                    
                    if text_parts:
                        return "\n".join(text_parts)

            logger.error(f"Could not extract text from Gemini response. Raw: {response}")
            return ""

        except Exception as e:
            logger.error(f"Error extracting response text: {e}")
            return ""

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
    logger.warning(f"processing_tasks: {processing_tasks}")
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
        'message': task['message'],
        'elapsed_time': elapsed_time,
        'cancellable': task['status'] in ['queued', 'processing'],
        'is_cancelled': cancel_flags.get(task_id, False)
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

@app.route("/api/download_youtube", methods=["POST"])
def download_youtube_video_api():
    """API endpoint to download YouTube video"""
    try:
        data = request.get_json()
        video_url = data.get("video_url")
        
        if not video_url:
            return jsonify({
                "success": False,
                "message": "Video URL is required"
            }), 400
        
        # Generate task ID for tracking
        task_id = hashlib.md5(f"{datetime.now().isoformat()}{video_url}".encode()).hexdigest()
        
        # Initialize task
        processing_tasks[task_id] = {
            "status": "queued",  # Bắt đầu từ queued
            "start_time": datetime.now(),
            "video_url": video_url,
            "type": "youtube_download",
            "message": "Initializing download..."
        }
        cancel_flags[task_id] = False
        
        # Start download in background
        socketio.start_background_task(
            download_youtube_task,
            task_id,
            video_url
        )
        
        return jsonify({
            "success": True,
            "task_id": task_id,
            "message": "Download started"
        })
        
    except Exception as e:
        logger.error(f"YouTube download API error: {e}")
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500
        
def download_youtube_task(task_id, video_url):
    """Background task for YouTube download with progress tracking"""
    try:
        output_dir = os.path.join(OUTPUT_FOLDER, "youtube_downloads")
        os.makedirs(output_dir, exist_ok=True)
        
        def progress_hook(d):
            if cancel_flags.get(task_id):
                raise InterruptedError("Download cancelled")
                
            if d["status"] == "downloading":
                try:
                    # Extract progress information
                    downloaded = d.get("downloaded_bytes", 0)
                    total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                    speed = d.get("speed", 0)
                    eta = d.get("eta", 0)
                    
                    progress = 0
                    if total > 0:
                        progress = (downloaded / total) * 100
                    
                    # Format speed
                    speed_str = ""
                    if speed:
                        if speed > 1024 * 1024:
                            speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
                        else:
                            speed_str = f"{speed / 1024:.2f} KB/s"
                    
                    # Emit progress
                    socketio.emit("download_progress", {
                        "task_id": task_id,
                        "status": "downloading",
                        "progress": round(progress, 1),
                        "downloaded": downloaded,
                        "total": total,
                        "speed": speed_str,
                        "eta": eta,
                        "message": f"Downloading... {progress:.1f}%"
                    }, room=task_id)
                    
                    socketio.sleep(0)
                    
                except Exception as e:
                    logger.warning(f"Progress hook error: {e}")
        
        # Download options
        ydl_opts = {
            "format": "best[height<=1080]",
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [progress_hook],
            "ignoreerrors": False,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            if cancel_flags.get(task_id):
                raise InterruptedError("Download cancelled")
                
            # Extract info
            info = ydl.extract_info(video_url, download=True)
            
            if info:
                filename = ydl.prepare_filename(info)
                file_size = os.path.getsize(filename)
                
                # Update task
                processing_tasks[task_id]["status"] = "completed"
                processing_tasks[task_id]["filename"] = os.path.basename(filename)
                processing_tasks[task_id]["filepath"] = filename
                processing_tasks[task_id]["title"] = info.get("title", "Unknown")
                processing_tasks[task_id]["file_size"] = file_size
                processing_tasks[task_id]["duration"] = info.get("duration", 0)
                
                # Emit completion
                socketio.emit("download_progress", {
                    "task_id": task_id,
                    "status": "completed",
                    "progress": 100,
                    "filename": os.path.basename(filename),
                    "download_url": f"/download_youtube/{task_id}",
                    "title": info.get("title", "Unknown"),
                    "file_size": file_size,
                    "message": "Download completed successfully!"
                }, room=task_id)
                
                logger.info(f"YouTube download completed: {filename}")
                
    except InterruptedError:
        logger.info(f"YouTube download cancelled: {task_id}")
        processing_tasks[task_id]["status"] = "cancelled"
        socketio.emit("download_progress", {
            "task_id": task_id,
            "status": "cancelled",
            "message": "Download was cancelled"
        }, room=task_id)
        
    except Exception as e:
        logger.error(f"YouTube download error: {e}")
        processing_tasks[task_id]["status"] = "error"
        socketio.emit("download_progress", {
            "task_id": task_id,
            "status": "error",
            "message": f"Download failed: {str(e)}"
        }, room=task_id)


@app.route("/download_youtube/<task_id>")
def download_youtube_file(task_id):
    """Download the completed YouTube video"""
    try:
        if task_id not in processing_tasks:
            return jsonify({"error": "Task not found"}), 404
        
        task = processing_tasks[task_id]
        
        if task["status"] != "completed":
            return jsonify({"error": "Download not completed"}), 400
        
        filepath = task.get("filepath")
        if not filepath or not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=task.get("filename", "video.mp4")
        )
        
    except Exception as e:
        logger.error(f"File download error: {e}")
        return jsonify({"error": "Download failed"}), 500

@app.route("/youtube_downloader", methods=["GET"])
def youtube_downloader():
    """Page to download YouTube videos only (no subtitle processing)"""
    return render_template("youtube_downloader.html")

# SocketIO event for YouTube download

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