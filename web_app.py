import os
import hashlib
import json
import pickle
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import threading
import time
import logging
from video_subtitle_processor import VideoSubtitleProcessor
import yt_dlp

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this')

# Cấu hình
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output'
CACHE_FOLDER = 'cache'
TEMP_FOLDER = 'temp'

# Tạo các thư mục cần thiết
for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, CACHE_FOLDER, TEMP_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# Cấu hình file types
ALLOWED_EXTENSIONS = {
    'video': ['mp4', 'avi', 'mov', 'mkv', 'wmv', 'flv', 'webm', '3gp'],
    'audio': ['mp3', 'wav', 'aac', 'flac', 'ogg', 'm4a']
}

# Danh sách ngôn ngữ hỗ trợ mở rộng
SUPPORTED_LANGUAGES = {
    'vietnamese': {'code': 'vi', 'name': 'Tiếng Việt', 'native': 'Tiếng Việt', 'flag': '🇻🇳'},
    'english': {'code': 'en', 'name': 'English', 'native': 'English', 'flag': '🇺🇸'},
    'chinese': {'code': 'zh-cn', 'name': 'Chinese (Simplified)', 'native': '中文 (简体)', 'flag': '🇨🇳'},
    'chinese_traditional': {'code': 'zh-tw', 'name': 'Chinese (Traditional)', 'native': '中文 (繁體)', 'flag': '🇹🇼'},
    'japanese': {'code': 'ja', 'name': 'Japanese', 'native': '日本語', 'flag': '🇯🇵'},
    'korean': {'code': 'ko', 'name': 'Korean', 'native': '한국어', 'flag': '🇰🇷'},
    'french': {'code': 'fr', 'name': 'French', 'native': 'Français', 'flag': '🇫🇷'},
    'spanish': {'code': 'es', 'name': 'Spanish', 'native': 'Español', 'flag': '🇪🇸'},
    'german': {'code': 'de', 'name': 'German', 'native': 'Deutsch', 'flag': '🇩🇪'},
    'italian': {'code': 'it', 'name': 'Italian', 'native': 'Italiano', 'flag': '🇮🇹'},
    'portuguese': {'code': 'pt', 'name': 'Portuguese', 'native': 'Português', 'flag': '🇵🇹'},
    'russian': {'code': 'ru', 'name': 'Russian', 'native': 'Русский', 'flag': '🇷🇺'},
    'arabic': {'code': 'ar', 'name': 'Arabic', 'native': 'العربية', 'flag': '🇸🇦'},
    'thai': {'code': 'th', 'name': 'Thai', 'native': 'ไทย', 'flag': '🇹🇭'},
    'hindi': {'code': 'hi', 'name': 'Hindi', 'native': 'हिन्दी', 'flag': '🇮🇳'},
    'indonesian': {'code': 'id', 'name': 'Indonesian', 'native': 'Bahasa Indonesia', 'flag': '🇮🇩'},
    'malaysian': {'code': 'ms', 'name': 'Malaysian', 'native': 'Bahasa Malaysia', 'flag': '🇲🇾'},
    'dutch': {'code': 'nl', 'name': 'Dutch', 'native': 'Nederlands', 'flag': '🇳🇱'},
    'swedish': {'code': 'sv', 'name': 'Swedish', 'native': 'Svenska', 'flag': '🇸🇪'},
    'norwegian': {'code': 'no', 'name': 'Norwegian', 'native': 'Norsk', 'flag': '🇳🇴'},
    'danish': {'code': 'da', 'name': 'Danish', 'native': 'Dansk', 'flag': '🇩🇰'},
    'polish': {'code': 'pl', 'name': 'Polish', 'native': 'Polski', 'flag': '🇵🇱'},
    'czech': {'code': 'cs', 'name': 'Czech', 'native': 'Čeština', 'flag': '🇨🇿'},
    'hungarian': {'code': 'hu', 'name': 'Hungarian', 'native': 'Magyar', 'flag': '🇭🇺'},
    'turkish': {'code': 'tr', 'name': 'Turkish', 'native': 'Türkçe', 'flag': '🇹🇷'},
    'greek': {'code': 'el', 'name': 'Greek', 'native': 'Ελληνικά', 'flag': '🇬🇷'},
    'hebrew': {'code': 'he', 'name': 'Hebrew', 'native': 'עברית', 'flag': '🇮🇱'},
    'finnish': {'code': 'fi', 'name': 'Finnish', 'native': 'Suomi', 'flag': '🇫🇮'},
    'ukrainian': {'code': 'uk', 'name': 'Ukrainian', 'native': 'Українська', 'flag': '🇺🇦'},
    'bulgarian': {'code': 'bg', 'name': 'Bulgarian', 'native': 'Български', 'flag': '🇧🇬'},
    'romanian': {'code': 'ro', 'name': 'Romanian', 'native': 'Română', 'flag': '🇷🇴'},
    'croatian': {'code': 'hr', 'name': 'Croatian', 'native': 'Hrvatski', 'flag': '🇭🇷'},
    'serbian': {'code': 'sr', 'name': 'Serbian', 'native': 'Српски', 'flag': '🇷🇸'},
    'slovenian': {'code': 'sl', 'name': 'Slovenian', 'native': 'Slovenščina', 'flag': '🇸🇮'},
    'slovak': {'code': 'sk', 'name': 'Slovak', 'native': 'Slovenčina', 'flag': '🇸🇰'},
    'lithuanian': {'code': 'lt', 'name': 'Lithuanian', 'native': 'Lietuvių', 'flag': '🇱🇹'},
    'latvian': {'code': 'lv', 'name': 'Latvian', 'native': 'Latviešu', 'flag': '🇱🇻'},
    'estonian': {'code': 'et', 'name': 'Estonian', 'native': 'Eesti', 'flag': '🇪🇪'},
}

# Global variables cho task tracking
processing_tasks = {}
processor = None

def init_processor():
    """Khởi tạo processor với cấu hình từ environment variables"""
    global processor
    gemini_api_key = os.environ.get('GEMINI_API_KEY')
    model_size = os.environ.get('WHISPER_MODEL_SIZE', 'base')
    
    processor = VideoSubtitleProcessor(
        model_size=model_size,
        gemini_api_key=gemini_api_key
    )
    logger.info(f"Đã khởi tạo processor với model: {model_size}")

def allowed_file(filename, file_type='video'):
    """Kiểm tra file có hợp lệ không"""
    return ('.' in filename and 
            filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS[file_type])

def get_file_hash(file_path):
    """Tạo hash cho file để cache"""
    with open(file_path, 'rb') as f:
        file_hash = hashlib.md5()
        chunk = f.read(8192)
        while chunk:
            file_hash.update(chunk)
            chunk = f.read(8192)
    return file_hash.hexdigest()

def get_cache_path(file_hash, cache_type='transcription'):
    """Lấy đường dẫn cache"""
    return os.path.join(CACHE_FOLDER, f"{file_hash}_{cache_type}.pkl")

def save_to_cache(data, file_hash, cache_type='transcription'):
    """Lưu data vào cache"""
    cache_path = get_cache_path(file_hash, cache_type)
    try:
        with open(cache_path, 'wb') as f:
            pickle.dump(data, f)
        logger.info(f"Đã lưu cache: {cache_path}")
        return True
    except Exception as e:
        logger.error(f"Lỗi lưu cache: {e}")
        return False

def load_from_cache(file_hash, cache_type='transcription'):
    """Tải data từ cache"""
    cache_path = get_cache_path(file_hash, cache_type)
    try:
        if os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                data = pickle.load(f)
            logger.info(f"Đã tải cache: {cache_path}")
            return data
    except Exception as e:
        logger.error(f"Lỗi tải cache: {e}")
    return None

def download_youtube_video(url, output_path):
    """Download video từ YouTube hoặc các platform khác"""
    try:
        ydl_opts = {
            'format': 'best[height<=720]',  # Chọn chất lượng tối đa 720p
            'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
            'ignoreerrors': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Lấy tên file đã download
            if info:
                filename = ydl.prepare_filename(info)
                return filename, info.get('title', 'Unknown')
            
    except Exception as e:
        logger.error(f"Lỗi download video: {e}")
        return None, str(e)
    
    return None, "Không thể download video"

def process_video_task(task_id, video_path, target_languages, options):
    """Xử lý video trong background thread"""
    global processing_tasks, processor
    
    try:
        # Cập nhật trạng thái
        processing_tasks[task_id]['status'] = 'processing'
        processing_tasks[task_id]['progress'] = 10
        processing_tasks[task_id]['message'] = 'Đang kiểm tra cache...'
        
        # Tạo file hash cho cache
        file_hash = get_file_hash(video_path)
        
        # Kiểm tra cache transcription
        cached_transcription = load_from_cache(file_hash, 'transcription')
        
        if cached_transcription:
            logger.info("Sử dụng transcription từ cache")
            processing_tasks[task_id]['progress'] = 60
            processing_tasks[task_id]['message'] = 'Đang sử dụng transcription từ cache...'
            result = cached_transcription
        else:
            # Transcribe video
            processing_tasks[task_id]['progress'] = 20
            processing_tasks[task_id]['message'] = 'Đang nhận dạng giọng nói...'
            
            result = processor.extract_audio_and_transcribe(video_path, OUTPUT_FOLDER)
            
            # Lưu vào cache
            save_to_cache(result, file_hash, 'transcription')
            processing_tasks[task_id]['progress'] = 60
        
        # Cải thiện timing
        processing_tasks[task_id]['progress'] = 70
        processing_tasks[task_id]['message'] = 'Đang cải thiện timing subtitle...'
        
        improved_segments = processor.improve_subtitle_timing(
            result['segments'],
            max_chars_per_line=options.get('max_chars', 50),
            max_duration=options.get('max_duration', 6.0)
        )
        
        # Tạo file SRT gốc
        processing_tasks[task_id]['progress'] = 75
        processing_tasks[task_id]['message'] = 'Đang tạo file subtitle gốc...'
        
        base_name = Path(video_path).stem
        original_srt_path = os.path.join(OUTPUT_FOLDER, f"{base_name}_original.srt")
        processor.create_srt_from_segments(improved_segments, original_srt_path)
        
        # Dịch sang các ngôn ngữ khác
        processing_tasks[task_id]['progress'] = 80
        processing_tasks[task_id]['message'] = 'Đang dịch sang các ngôn ngữ khác...'
        
        translated_files = {}
        if target_languages and processor.use_gemini:
            translated_files = processor.translate_srt_with_gemini(
                original_srt_path, target_languages, OUTPUT_FOLDER
            )
        elif target_languages:
            translated_files = processor.translate_srt_fallback(
                original_srt_path, target_languages, OUTPUT_FOLDER
            )
        
        # Hoàn thành
        processing_tasks[task_id]['status'] = 'completed'
        processing_tasks[task_id]['progress'] = 100
        processing_tasks[task_id]['message'] = 'Hoàn thành!'
        processing_tasks[task_id]['results'] = {
            'original_srt': original_srt_path,
            'translated_files': translated_files,
            'segments_count': len(improved_segments),
            'file_hash': file_hash
        }
        
        logger.info(f"Hoàn thành xử lý task {task_id}")
        
    except Exception as e:
        logger.error(f"Lỗi xử lý task {task_id}: {e}")
        processing_tasks[task_id]['status'] = 'error'
        processing_tasks[task_id]['message'] = f'Lỗi: {str(e)}'

@app.route('/')
def index():
    """Trang chủ"""
    return render_template('index.html', languages=SUPPORTED_LANGUAGES)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Upload file hoặc xử lý URL"""
    try:
        video_path = None
        original_filename = None
        
        # Tạo task ID
        task_id = hashlib.md5(f"{datetime.now().isoformat()}".encode()).hexdigest()
        
        # Lấy parameters
        target_languages = request.form.getlist('languages')
        options = {
            'max_chars': int(request.form.get('max_chars', 50)),
            'max_duration': float(request.form.get('max_duration', 6.0)),
            'model_size': request.form.get('model_size', 'base')
        }
        
        # Kiểm tra nguồn input: file upload hay URL
        if 'file' in request.files and request.files['file'].filename:
            # Upload file
            file = request.files['file']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}_{filename}"
                video_path = os.path.join(UPLOAD_FOLDER, filename)
                file.save(video_path)
                original_filename = file.filename
                logger.info(f"Đã upload file: {video_path}")
        
        elif request.form.get('video_url'):
            # Download từ URL
            video_url = request.form.get('video_url')
            logger.info(f"Đang download từ URL: {video_url}")
            
            # Khởi tạo task để hiển thị progress download
            processing_tasks[task_id] = {
                'status': 'downloading',
                'progress': 0,
                'message': 'Đang download video từ URL...',
                'start_time': datetime.now(),
                'results': None
            }
            
            # Download video
            downloaded_path, title = download_youtube_video(video_url, UPLOAD_FOLDER)
            if downloaded_path and os.path.exists(downloaded_path):
                video_path = downloaded_path
                original_filename = title or "Downloaded Video"
                logger.info(f"Đã download video: {video_path}")
            else:
                return jsonify({
                    'success': False,
                    'message': f'Không thể download video: {title}'
                })
        
        if not video_path:
            return jsonify({
                'success': False,
                'message': 'Vui lòng chọn file video hoặc nhập URL'
            })
        
        # Khởi tạo task
        processing_tasks[task_id] = {
            'status': 'queued',
            'progress': 0,
            'message': 'Đang chuẩn bị xử lý...',
            'start_time': datetime.now(),
            'video_path': video_path,
            'original_filename': original_filename,
            'target_languages': target_languages,
            'results': None
        }
        
        # Bắt đầu xử lý trong background
        thread = threading.Thread(
            target=process_video_task,
            args=(task_id, video_path, target_languages, options)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': 'Đã bắt đầu xử lý video'
        })
        
    except Exception as e:
        logger.error(f"Lỗi upload: {e}")
        return jsonify({
            'success': False,
            'message': f'Lỗi xử lý: {str(e)}'
        })

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

@app.route('/download/<path:filename>')
def download_file(filename):
    """Download file subtitle"""
    try:
        file_path = os.path.join(OUTPUT_FOLDER, filename)
        if os.path.exists(file_path):
            return send_file(
                file_path,
                as_attachment=True,
                download_name=filename
            )
        else:
            flash('File không tồn tại', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        logger.error(f"Lỗi download file: {e}")
        flash('Lỗi download file', 'error')
        return redirect(url_for('index'))

@app.route('/history')
def history():
    """Xem lịch sử xử lý"""
    completed_tasks = []
    for task_id, task in processing_tasks.items():
        if task['status'] == 'completed':
            completed_tasks.append({
                'task_id': task_id,
                'filename': task.get('original_filename', 'Unknown'),
                'start_time': task['start_time'],
                'languages': task.get('target_languages', []),
                'segments_count': task.get('results', {}).get('segments_count', 0)
            })
    
    # Sắp xếp theo thời gian mới nhất
    completed_tasks.sort(key=lambda x: x['start_time'], reverse=True)
    
    return render_template('history.html', tasks=completed_tasks)

@app.route('/clear_cache')
def clear_cache():
    """Xóa cache"""
    try:
        import glob
        cache_files = glob.glob(os.path.join(CACHE_FOLDER, '*.pkl'))
        removed_count = 0
        for file_path in cache_files:
            os.remove(file_path)
            removed_count += 1
        
        flash(f'Đã xóa {removed_count} file cache', 'success')
    except Exception as e:
        logger.error(f"Lỗi xóa cache: {e}")
        flash('Lỗi xóa cache', 'error')
    
    return redirect(url_for('index'))

@app.route('/api/languages')
def api_languages():
    """API trả về danh sách ngôn ngữ"""
    return jsonify(SUPPORTED_LANGUAGES)

@app.route('/api/stats')
def api_stats():
    """API thống kê"""
    cache_files = len([f for f in os.listdir(CACHE_FOLDER) if f.endswith('.pkl')])
    completed_tasks = len([t for t in processing_tasks.values() if t['status'] == 'completed'])
    
    return jsonify({
        'cache_files': cache_files,
        'completed_tasks': completed_tasks,
        'active_tasks': len([t for t in processing_tasks.values() if t['status'] in ['queued', 'processing']]),
        'supported_languages': len(SUPPORTED_LANGUAGES)
    })

if __name__ == '__main__':
    # Khởi tạo processor
    init_processor()
    
    # Chạy app
    port = int(os.environ.get('PORT', 5050))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Khởi động web app tại port {port}")
    logger.info(f"Debug mode: {debug_mode}")
    logger.info(f"Hỗ trợ {len(SUPPORTED_LANGUAGES)} ngôn ngữ")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug_mode,
        threaded=True
    )