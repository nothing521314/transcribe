import whisper
import os
import re
from datetime import timedelta
import pysrt
from pathlib import Path
import argparse
import logging
import google.generativeai as genai
from typing import List, Dict, Optional
import time
import random
from functools import wraps

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def retry_with_exponential_backoff(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True
):
    """
    Decorator cho retry với exponential backoff
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_msg = str(e).lower()
                    
                    # Kiểm tra các lỗi có thể retry
                    retryable_errors = [
                        '504', 'timeout', 'deadline exceeded', 
                        'rate limit', 'too many requests',
                        'internal server error', '500', '502', '503'
                    ]
                    
                    is_retryable = any(error in error_msg for error in retryable_errors)
                    
                    if not is_retryable or attempt == max_retries:
                        logger.error(f"Lỗi không thể retry hoặc đã hết lần thử: {e}")
                        raise e
                    
                    # Tính delay với exponential backoff
                    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                    
                    # Thêm jitter để tránh thundering herd
                    if jitter:
                        delay += random.uniform(0, delay * 0.1)
                    
                    logger.warning(f"Thử lại lần {attempt + 1}/{max_retries} sau {delay:.2f}s. Lỗi: {e}")
                    time.sleep(delay)
            
            raise last_exception
        return wrapper
    return decorator

class VideoSubtitleProcessor:
    def __init__(self, model_size='base', gemini_api_key=None, max_retries=5):
        """
        Khởi tạo processor với mô hình Whisper và Gemini AI
        model_size: 'tiny', 'base', 'small', 'medium', 'large'
        gemini_api_key: API key cho Google Gemini AI
        max_retries: Số lần retry tối đa
        """
        logger.info(f"Đang tải mô hình Whisper '{model_size}'...")
        self.model = whisper.load_model(model_size)
        self.max_retries = max_retries
        
        # Thiết lập Gemini AI
        if gemini_api_key:
            genai.configure(api_key=gemini_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-2.5-pro')
            self.use_gemini = True
            logger.info("Đã khởi tạo Gemini AI")
            logger.info(f"API KEY: {gemini_api_key}")
        else:
            self.use_gemini = False
            logger.warning("Không có API key Gemini, sẽ sử dụng Google Translate")
            from googletrans import Translator
            self.translator = Translator()
        
        # Mapping ngôn ngữ với tên đầy đủ
        self.language_mapping = {
            'vietnamese': {'code': 'vi', 'name': 'tiếng Việt', 'native': 'Tiếng Việt'},
            'chinese': {'code': 'zh-cn', 'name': 'tiếng Trung', 'native': '中文'},
            'korean': {'code': 'ko', 'name': 'tiếng Hàn', 'native': '한국어'},
            'french': {'code': 'fr', 'name': 'tiếng Pháp', 'native': 'Français'},
            'spanish': {'code': 'es', 'name': 'tiếng Tây Ban Nha', 'native': 'Español'},
            'german': {'code': 'de', 'name': 'tiếng Đức', 'native': 'Deutsch'},
            'japanese': {'code': 'ja', 'name': 'tiếng Nhật', 'native': '日本語'},
            'thai': {'code': 'th', 'name': 'tiếng Thái', 'native': 'ไทย'},
            'russian': {'code': 'ru', 'name': 'tiếng Nga', 'native': 'Русский'},
            'arabic': {'code': 'ar', 'name': 'tiếng Ả Rập', 'native': 'العربية'},
            'portuguese': {'code': 'pt', 'name': 'tiếng Bồ Đào Nha', 'native': 'Português'},
            'italian': {'code': 'it', 'name': 'tiếng Ý', 'native': 'Italiano'},
        }
        
        # Thống kê retry
        self.retry_stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_retries': 0
        }
    
    def extract_audio_and_transcribe(self, video_path: str, output_dir: Optional[str] = None) -> Dict:
        """
        Trích xuất audio từ video và tạo transcript với timestamps chính xác
        """
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        logger.info(f"Đang xử lý video: {video_path}")
        
        # Transcribe với cài đặt tối ưu cho độ chính xác cao
        result = self.model.transcribe(
            video_path, 
            word_timestamps=True,
            verbose=True,
            language='en',  # Xác định ngôn ngữ gốc là tiếng Anh
            temperature=0,  # Giảm random để tăng tính nhất quán
            best_of=5,      # Thử nhiều lần để chọn kết quả tốt nhất
            beam_size=5,    # Tăng beam size cho kết quả tốt hơn
            patience=1.0,   # Tăng patience để tránh kết thúc sớm
        )
        
        logger.info(f"Đã nhận dạng được {len(result['segments'])} segments")
        return result
    
    def create_srt_from_segments(self, segments: List[Dict], output_path: str) -> str:
        """
        Tạo file .srt từ segments với timestamps chính xác
        """
        srt_content = []
        
        for i, segment in enumerate(segments, 1):
            start_time = self.seconds_to_srt_time(segment['start'])
            end_time = self.seconds_to_srt_time(segment['end'])
            text = segment['text'].strip()
            
            # Làm sạch text
            text = self.clean_subtitle_text(text)
            
            srt_entry = f"{i}\n{start_time} --> {end_time}\n{text}\n"
            srt_content.append(srt_entry)
        
        # Ghi file SRT
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(srt_content))
        
        logger.info(f"Đã tạo file SRT: {output_path}")
        return output_path
    
    def clean_subtitle_text(self, text: str) -> str:
        """
        Làm sạch text subtitle
        """
        # Loại bỏ ký tự đặc biệt và khoảng trắng thừa
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        # Chuẩn hóa dấu câu
        text = re.sub(r'\s*([,.!?;:])\s*', r'\1 ', text)
        text = text.strip()
        
        return text
    
    def seconds_to_srt_time(self, seconds: float) -> str:
        """
        Chuyển đổi seconds sang định dạng SRT time (HH:MM:SS,mmm)
        """
        td = timedelta(seconds=seconds)
        hours = int(td.total_seconds() // 3600)
        minutes = int((td.total_seconds() % 3600) // 60)
        secs = int(td.total_seconds() % 60)
        milliseconds = int((td.total_seconds() % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    
    def improve_subtitle_timing(self, segments: List[Dict], 
                               max_chars_per_line: int = 50, 
                               max_duration: float = 6.0,
                               min_duration: float = 1.0) -> List[Dict]:
        """
        Cải thiện timing và chia nhỏ subtitle cho dễ đọc
        """
        improved_segments = []
        
        for segment in segments:
            text = segment['text'].strip()
            start_time = segment['start']
            end_time = segment['end']
            duration = end_time - start_time
            
            # Đảm bảo thời gian tối thiểu
            if duration < min_duration:
                end_time = start_time + min_duration
                duration = min_duration
            
            # Chia nhỏ text nếu quá dài
            if len(text) > max_chars_per_line or duration > max_duration:
                chunks = self.split_text_intelligently(text, max_chars_per_line)
                
                # Phân chia thời gian cho các chunks
                chunk_duration = min(duration / len(chunks), max_duration)
                
                for i, chunk in enumerate(chunks):
                    chunk_start = start_time + (i * chunk_duration)
                    chunk_end = min(
                        chunk_start + chunk_duration,
                        end_time
                    )
                    
                    # Đảm bảo không bị chồng lấp với segment tiếp theo
                    if chunk_end > end_time:
                        chunk_end = end_time
                    
                    improved_segments.append({
                        'start': chunk_start,
                        'end': chunk_end,
                        'text': chunk.strip()
                    })
            else:
                improved_segments.append({
                    'start': start_time,
                    'end': end_time,
                    'text': text
                })
        
        return improved_segments
    
    def split_text_intelligently(self, text: str, max_chars: int) -> List[str]:
        """
        Chia text một cách thông minh theo câu và cụm từ
        """
        if len(text) <= max_chars:
            return [text]
        
        # Ưu tiên chia theo câu
        sentences = re.split(r'([.!?]+)', text)
        chunks = []
        current_chunk = ""
        
        for i in range(0, len(sentences), 2):
            sentence = sentences[i] if i < len(sentences) else ""
            punctuation = sentences[i+1] if i+1 < len(sentences) else ""
            full_sentence = sentence + punctuation
            
            if len(current_chunk + full_sentence) <= max_chars:
                current_chunk += full_sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = full_sentence
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Nếu vẫn có chunk quá dài, chia theo từ
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > max_chars:
                final_chunks.extend(self.split_by_words(chunk, max_chars))
            else:
                final_chunks.append(chunk)
        
        return final_chunks
    
    def split_by_words(self, text: str, max_chars: int) -> List[str]:
        """
        Chia text theo từ khi không thể chia theo câu
        """
        words = text.split()
        chunks = []
        current_chunk = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + 1 <= max_chars:
                current_chunk.append(word)
                current_length += len(word) + 1
            else:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                current_chunk = [word]
                current_length = len(word)
        
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        
        return chunks
    
    @retry_with_exponential_backoff(max_retries=5, base_delay=2.0, max_delay=120.0)
    def translate_with_gemini_single_request(self, texts: List[str], target_language: str, context: str = "") -> List[str]:
        """
        Dịch danh sách text sử dụng Gemini AI với retry mechanism
        """
        self.retry_stats['total_requests'] += 1
        
        lang_info = self.language_mapping.get(target_language.lower())
        if not lang_info:
            raise ValueError(f"Không hỗ trợ ngôn ngữ: {target_language}")
        
        # Tạo prompt cho Gemini với batch size nhỏ hơn
        prompt = f"""
Bạn là một chuyên gia dịch thuật chuyên nghiệp. Hãy dịch các đoạn subtitle tiếng Anh sau sang {lang_info['name']} ({lang_info['native']}).

YÊU CẦU QUAN TRỌNG:
1. Dịch theo nghĩa và ngữ cảnh, KHÔNG dịch từng từ một
2. Giữ nguyên độ dài tương đối của câu gốc để phù hợp với timing
3. Sử dụng ngôn ngữ tự nhiên, dễ hiểu
4. Giữ nguyên tông giọng và cảm xúc của câu gốc
5. Với thuật ngữ chuyên môn, hãy dịch theo cách phổ biến nhất
6. Đảm bảo tính nhất quán trong suốt quá trình dịch

{f"NGỮ CẢNH: {context}" if context else ""}

CÁC ĐOẠN CẦN DỊCH:
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(texts)])}

Hãy trả về kết quả dịch theo định dạng:
1. [Bản dịch đoạn 1]
2. [Bản dịch đoạn 2]
...

CHỈ trả về bản dịch, không giải thích thêm.
"""
        
        # Tạo response với timeout setting
        response = self.gemini_model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.3,
                'top_p': 0.8,
                'top_k': 40,
                'max_output_tokens': 8192,
            }
        )
        
        translations = []
        
        # Parse kết quả từ Gemini
        lines = response.text.strip().split('\n')
        for line in lines:
            if line.strip():
                # Loại bỏ số thứ tự ở đầu
                translation = re.sub(r'^\d+\.\s*', '', line.strip())
                if translation:
                    translations.append(translation)
        
        # Đảm bảo số lượng bản dịch khớp với input
        if len(translations) != len(texts):
            logger.warning(f"Số lượng bản dịch ({len(translations)}) không khớp với input ({len(texts)})")
            # Bổ sung hoặc cắt bớt nếu cần
            while len(translations) < len(texts):
                translations.append(texts[len(translations)])
            translations = translations[:len(texts)]
        
        self.retry_stats['successful_requests'] += 1
        return translations
    
    def translate_with_gemini(self, texts: List[str], target_language: str, context: str = "") -> List[str]:
        """
        Wrapper cho translate_with_gemini_single_request với error handling
        """
        try:
            return self.translate_with_gemini_single_request(texts, target_language, context)
        except Exception as e:
            logger.error(f"Lỗi dịch sau {self.max_retries} lần thử: {e}")
            self.retry_stats['failed_requests'] += 1
            # Trả về text gốc nếu dịch thất bại hoàn toàn
            return texts
    
    def translate_srt_with_gemini(self, srt_path: str, target_languages: List[str], 
                                 output_dir: Optional[str] = None, batch_size: int = 15) -> Dict[str, str]:
        """
        Dịch file SRT sử dụng Gemini AI với xử lý theo batch và retry mechanism
        """
        if output_dir is None:
            output_dir = os.path.dirname(srt_path)
        
        # Đọc file SRT gốc
        subs = pysrt.open(srt_path, encoding='utf-8')
        base_name = Path(srt_path).stem.replace('_original', '')
        
        # Tạo ngữ cảnh từ toàn bộ transcript
        context = " ".join([sub.text for sub in subs[:10]])  # Lấy 10 câu đầu làm context
        
        translated_files = {}
        
        for lang_name in target_languages:
            if lang_name.lower() not in self.language_mapping:
                logger.warning(f"Không hỗ trợ ngôn ngữ: {lang_name}")
                continue
            
            logger.info(f"Đang dịch sang {lang_name}...")
            
            # Reset thống kê cho ngôn ngữ mới
            lang_stats = {
                'total_batches': 0,
                'successful_batches': 0,
                'failed_batches': 0,
                'total_retries': 0
            }
            
            # Chia subtitle thành các batch để xử lý
            all_texts = [sub.text for sub in subs]
            translated_texts = []
            
            # Tính toán số batch
            total_batches = (len(all_texts) + batch_size - 1) // batch_size
            
            for i in range(0, len(all_texts), batch_size):
                batch_num = i // batch_size + 1
                batch_texts = all_texts[i:i + batch_size]
                lang_stats['total_batches'] += 1
                
                logger.info(f"Đang xử lý batch {batch_num}/{total_batches} ({len(batch_texts)} dòng)")
                
                try:
                    if self.use_gemini:
                        batch_translations = self.translate_with_gemini(
                            batch_texts, lang_name, context
                        )
                        lang_stats['successful_batches'] += 1
                    else:
                        # Fallback to Google Translate
                        batch_translations = []
                        lang_code = self.language_mapping[lang_name.lower()]['code']
                        for text in batch_texts:
                            try:
                                translation = self.translator.translate(
                                    text, src='en', dest=lang_code
                                ).text
                                batch_translations.append(translation)
                            except:
                                batch_translations.append(text)  # Fallback to original
                        lang_stats['successful_batches'] += 1
                    
                    translated_texts.extend(batch_translations)
                    
                    # Delay động dựa trên tình trạng lỗi
                    base_delay = 1.5 if lang_stats['failed_batches'] == 0 else 3.0
                    time.sleep(base_delay + random.uniform(0, 1))
                    
                    logger.info(f"✓ Hoàn thành batch {batch_num}/{total_batches}")
                    
                except Exception as e:
                    logger.error(f"✗ Batch {batch_num} thất bại hoàn toàn: {e}")
                    lang_stats['failed_batches'] += 1
                    # Thêm text gốc nếu dịch thất bại
                    translated_texts.extend(batch_texts)
                    
                    # Tăng delay nếu có lỗi
                    time.sleep(5.0)
            
            # Báo cáo kết quả cho ngôn ngữ
            success_rate = (lang_stats['successful_batches'] / lang_stats['total_batches']) * 100
            logger.info(f"Kết quả dịch {lang_name}: {lang_stats['successful_batches']}/{lang_stats['total_batches']} batch thành công ({success_rate:.1f}%)")
            
            # Tạo file SRT đã dịch
            translated_subs = pysrt.SubRipFile()
            for i, (sub, translated_text) in enumerate(zip(subs, translated_texts)):
                new_sub = pysrt.SubRipItem(
                    index=sub.index,
                    start=sub.start,
                    end=sub.end,
                    text=translated_text
                )
                translated_subs.append(new_sub)
            
            # Lưu file
            output_file = os.path.join(output_dir, f"{base_name}_{lang_name.lower()}.srt")
            translated_subs.save(output_file, encoding='utf-8')
            translated_files[lang_name] = output_file
            logger.info(f"✓ Đã tạo file dịch: {output_file}")
        
        return translated_files
    
    def analyze_video_content(self, transcript_text: str) -> str:
        """
        Phân tích nội dung video để tạo context cho việc dịch
        """
        if not self.use_gemini:
            return ""
        
        prompt = f"""
Hãy phân tích nội dung của đoạn transcript sau và tóm tắt ngắn gọn:
- Chủ đề chính
- Loại hình nội dung (giáo dục, giải trí, tin tức, v.v.)
- Tông giọng chung
- Các thuật ngữ chuyên môn quan trọng

Transcript:
{transcript_text[:2000]}...

Trả về kết quả trong 2-3 câu ngắn.
"""
        
        try:
            response = self.gemini_model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Lỗi phân tích nội dung: {e}")
            return ""
    
    def process_video_complete(self, video_path: str, target_languages: Optional[List[str]] = None, 
                              output_dir: Optional[str] = None, model_size: str = 'base') -> Dict:
        """
        Xử lý hoàn chỉnh: tạo subtitle gốc và dịch sang các ngôn ngữ với AI
        """
        if target_languages is None:
            target_languages = ['vietnamese', 'chinese', 'korean', 'french']
        
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        # Tạo thư mục output nếu chưa có
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Bước 1: Transcribe video
            logger.info("Bước 1: Trích xuất và nhận dạng giọng nói...")
            result = self.extract_audio_and_transcribe(video_path, output_dir)
            
            # Bước 2: Phân tích nội dung
            content_analysis = ""
            if self.use_gemini:
                logger.info("Bước 2: Phân tích nội dung video...")
                full_text = " ".join([seg['text'] for seg in result['segments']])
                content_analysis = self.analyze_video_content(full_text)
                logger.info(f"Phân tích nội dung: {content_analysis}")
            
            # Bước 3: Cải thiện timing
            logger.info("Bước 3: Cải thiện timing subtitle...")
            improved_segments = self.improve_subtitle_timing(result['segments'])
            
            # Bước 4: Tạo file SRT gốc
            logger.info("Bước 4: Tạo file subtitle gốc...")
            base_name = Path(video_path).stem
            original_srt_path = os.path.join(output_dir, f"{base_name}_original.srt")
            self.create_srt_from_segments(improved_segments, original_srt_path)
            
            # Bước 5: Dịch sang các ngôn ngữ khác
            logger.info("Bước 5: Dịch sang các ngôn ngữ khác với AI...")
            if self.use_gemini:
                translated_files = self.translate_srt_with_gemini(
                    original_srt_path, target_languages, output_dir
                )
            else:
                translated_files = self.translate_srt_fallback(
                    original_srt_path, target_languages, output_dir
                )
            
            results = {
                'original_srt': original_srt_path,
                'translated_files': translated_files,
                'transcription': result,
                'content_analysis': content_analysis,
                'retry_stats': self.retry_stats
            }
            
            logger.info("Hoàn thành xử lý video!")
            self.print_final_stats()
            return results
            
        except Exception as e:
            logger.error(f"Lỗi xử lý video: {e}")
            raise
    
    def print_final_stats(self):
        """
        In thống kê cuối cùng về quá trình dịch
        """
        stats = self.retry_stats
        if stats['total_requests'] > 0:
            success_rate = (stats['successful_requests'] / stats['total_requests']) * 100
            logger.info(f"\n📊 THỐNG KÊ DỊCH:")
            logger.info(f"   Tổng requests: {stats['total_requests']}")
            logger.info(f"   Thành công: {stats['successful_requests']} ({success_rate:.1f}%)")
            logger.info(f"   Thất bại: {stats['failed_requests']}")
            logger.info(f"   Tổng retry: {stats['total_retries']}")
    
    def translate_srt_fallback(self, srt_path: str, target_languages: List[str], 
                              output_dir: Optional[str] = None) -> Dict[str, str]:
        """
        Dịch file SRT sử dụng Google Translate (fallback)
        """
        if output_dir is None:
            output_dir = os.path.dirname(srt_path)
        
        subs = pysrt.open(srt_path, encoding='utf-8')
        base_name = Path(srt_path).stem.replace('_original', '')
        translated_files = {}
        
        for lang_name in target_languages:
            if lang_name.lower() not in self.language_mapping:
                continue
            
            lang_code = self.language_mapping[lang_name.lower()]['code']
            logger.info(f"Đang dịch sang {lang_name} (fallback)...")
            
            translated_subs = pysrt.SubRipFile()
            
            for sub in subs:
                try:
                    translated_text = self.translator.translate(
                        sub.text, src='en', dest=lang_code
                    ).text
                    
                    new_sub = pysrt.SubRipItem(
                        index=sub.index,
                        start=sub.start,
                        end=sub.end,
                        text=translated_text
                    )
                    translated_subs.append(new_sub)
                    
                except Exception as e:
                    logger.error(f"Lỗi dịch dòng {sub.index}: {e}")
                    translated_subs.append(sub)
            
            output_file = os.path.join(output_dir, f"{base_name}_{lang_name.lower()}.srt")
            translated_subs.save(output_file, encoding='utf-8')
            translated_files[lang_name] = output_file
        
        return translated_files

def main():
    parser = argparse.ArgumentParser(description='Tạo và dịch subtitle cho video với AI - Phiên bản cải tiến')
    parser.add_argument('video_path', help='Đường dẫn đến file video')
    parser.add_argument('--output-dir', help='Thư mục output (mặc định: cùng thư mục với video)')
    parser.add_argument('--languages', nargs='+', 
                       default=['vietnamese', 'chinese', 'korean', 'french'],
                       help='Danh sách ngôn ngữ cần dịch')
    parser.add_argument('--model', default='base', 
                       choices=['tiny', 'base', 'small', 'medium', 'large'],
                       help='Kích thước mô hình Whisper')
    parser.add_argument('--gemini-api-key', help='API key cho Google Gemini AI')
    parser.add_argument('--batch-size', type=int, default=15,
                       help='Số lượng subtitle xử lý trong một batch (nhỏ hơn để giảm timeout)')
    parser.add_argument('--max-retries', type=int, default=5,
                       help='Số lần retry tối đa khi gặp lỗi')
    parser.add_argument('--base-delay', type=float, default=2.0,
                       help='Thời gian delay cơ bản giữa các retry (giây)')
    
    args = parser.parse_args()
    
    # Khởi tạo processor với cấu hình retry
    processor = VideoSubtitleProcessor(
        model_size=args.model,
        gemini_api_key=args.gemini_api_key,
        max_retries=args.max_retries
    )
    
    # Xử lý video
    try:
        results = processor.process_video_complete(
            video_path=args.video_path,
            target_languages=args.languages,
            output_dir=args.output_dir,
            model_size=args.model
        )
        
        print("\n" + "="*80)
        print("KẾT QUẢ XỬ LÝ")
        print("="*80)
        print(f"File subtitle gốc: {results['original_srt']}")
        
        if results.get('content_analysis'):
            print(f"\nPhân tích nội dung: {results['content_analysis']}")
        
        print("\nCác file dịch:")
        for lang, file_path in results['translated_files'].items():
            print(f"  - {lang.capitalize()}: {file_path}")
        
        print(f"\nTổng cộng: {len(results['transcription']['segments'])} đoạn subtitle")
        
        # Hiển thị thống kê retry nếu có
        if results.get('retry_stats'):
            stats = results['retry_stats']
            if stats['total_requests'] > 0:
                success_rate = (stats['successful_requests'] / stats['total_requests']) * 100
                print(f"\nThống kê dịch:")
                print(f"  - Tổng requests: {stats['total_requests']}")
                print(f"  - Thành công: {stats['successful_requests']} ({success_rate:.1f}%)")
                print(f"  - Thất bại: {stats['failed_requests']}")
        
    except KeyboardInterrupt:
        print("\n❌ Đã dừng xử lý theo yêu cầu người dùng")
    except Exception as e:
        print(f"\n❌ Lỗi xử lý: {e}")
        raise

if __name__ == "__main__":
    main()

# Sử dụng đơn giản trong Python script
"""
from video_subtitle_processor_improved import VideoSubtitleProcessor

# Khởi tạo với Gemini AI và cấu hình retry
processor = VideoSubtitleProcessor(
    model_size='base',
    gemini_api_key='your_gemini_api_key_here',
    max_retries=5
)

# Xử lý video với retry tự động
results = processor.process_video_complete(
    video_path='path/to/your/video.mp4',
    target_languages=['vietnamese', 'chinese', 'korean', 'french']
)

print(f"Subtitle gốc: {results['original_srt']}")
print(f"Các file dịch: {results['translated_files']}")
print(f"Phân tích nội dung: {results['content_analysis']}")
print(f"Thống kê retry: {results['retry_stats']}")

# Sử dụng với cấu hình tùy chỉnh
processor_custom = VideoSubtitleProcessor(
    model_size='large',  # Mô hình lớn hơn cho độ chính xác cao hơn
    gemini_api_key='your_api_key',
    max_retries=3  # Ít retry hơn nếu muốn xử lý nhanh
)

# Xử lý với batch size nhỏ để tránh timeout
results = processor_custom.translate_srt_with_gemini(
    'path/to/subtitle.srt',
    ['vietnamese', 'korean'],
    batch_size=10  # Batch nhỏ hơn
)
"""

# CÁCH SỬ DỤNG VỚI COMMAND LINE:
"""
# Cơ bản
python video_subtitle_processor_improved.py video.mp4 --gemini-api-key YOUR_API_KEY

# Với cấu hình tùy chỉnh
python video_subtitle_processor_improved.py video.mp4 \\
    --gemini-api-key YOUR_API_KEY \\
    --languages vietnamese chinese korean japanese \\
    --model large \\
    --batch-size 10 \\
    --max-retries 3 \\
    --output-dir ./subtitles/

# Chỉ dịch sang tiếng Việt với retry ít
python video_subtitle_processor_improved.py video.mp4 \\
    --gemini-api-key YOUR_API_KEY \\
    --languages vietnamese \\
    --batch-size 20 \\
    --max-retries 2
"""