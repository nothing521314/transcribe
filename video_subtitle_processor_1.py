# video_subtitle_processor.py

import whisper
import os
import re
import time
import hashlib
import pickle
from datetime import timedelta
from pathlib import Path
import argparse
import logging
import google.generativeai as genai
from typing import List, Dict, Optional
import concurrent.futures
import threading
import random

# Enhanced logging setup for Docker visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # This will show in Docker logs
        logging.FileHandler('logs/processor.log') if os.path.exists('logs') else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

class VideoSubtitleProcessor:
    """
    Enhanced Video Subtitle Processor with optimizations:
    - Smart caching system
    - Parallel translation with multiple API keys
    - Robust retry mechanism for API timeouts
    - Performance monitoring
    - Docker logs integration
    """
    
    def __init__(self, model_size='base', gemini_api_key=None, gemini_api_keys=None):
        """
        Initialize processor
        
        Args:
            model_size: Whisper model size
            gemini_api_key: Single API key (backward compatibility)
            gemini_api_keys: List of API keys for parallel processing
        """
        self.model_size = model_size
        
        # Handle both single and multiple API keys
        if gemini_api_keys:
            self.gemini_api_keys = gemini_api_keys
        elif gemini_api_key:
            self.gemini_api_keys = [gemini_api_key]
        else:
            self.gemini_api_keys = []
        
        self.use_gemini = len(self.gemini_api_keys) > 0
        self.current_api_index = 0
        
        # Retry configuration
        self.max_retries = 5
        self.base_delay = 1.0
        self.max_delay = 30.0
        self.timeout_seconds = 60  # Request timeout
        
        logger.info(f"🚀 Initializing Video Subtitle Processor")
        logger.info(f"📊 Model: {model_size}")
        logger.info(f"🔑 API Keys: {len(self.gemini_api_keys)}")
        logger.info(f"🔄 Max Retries: {self.max_retries}")
        
        # Load Whisper model
        self._load_whisper_model()
        
        # Initialize Gemini clients
        if self.use_gemini:
            self._initialize_gemini_clients()
        else:
            logger.warning("⚠️ No Gemini API keys - using fallback translation")
            try:
                from googletrans import Translator
                self.translator = Translator()
            except ImportError:
                logger.error("❌ googletrans not available")
                self.translator = None
        
        # Language mapping
        self.language_mapping = {
            'vietnamese': {'code': 'vi', 'name': 'tiếng Việt', 'native': 'Tiếng Việt'},
            'chinese': {'code': 'zh-cn', 'name': 'tiếng Trung', 'native': '中文 (简体)'},
            'chinese_traditional': {'code': 'zh-tw', 'name': 'tiếng Trung (phồn thể)', 'native': '中文 (繁體)'},
            'korean': {'code': 'ko', 'name': 'tiếng Hàn', 'native': '한국어'},
            'japanese': {'code': 'ja', 'name': 'tiếng Nhật', 'native': '日本語'},
            'french': {'code': 'fr', 'name': 'tiếng Pháp', 'native': 'Français'},
            'spanish': {'code': 'es', 'name': 'tiếng Tây Ban Nha', 'native': 'Español'},
            'german': {'code': 'de', 'name': 'tiếng Đức', 'native': 'Deutsch'},
            'italian': {'code': 'it', 'name': 'tiếng Ý', 'native': 'Italiano'},
            'portuguese': {'code': 'pt', 'name': 'tiếng Bồ Đào Nha', 'native': 'Português'},
            'russian': {'code': 'ru', 'name': 'tiếng Nga', 'native': 'Русский'},
            'arabic': {'code': 'ar', 'name': 'tiếng Ả Rập', 'native': 'العربية'},
            'thai': {'code': 'th', 'name': 'tiếng Thái', 'native': 'ไทย'},
            'hindi': {'code': 'hi', 'name': 'tiếng Hindi', 'native': 'हिन्दी'},
            'indonesian': {'code': 'id', 'name': 'tiếng Indonesia', 'native': 'Bahasa Indonesia'},
            'malaysian': {'code': 'ms', 'name': 'tiếng Malaysia', 'native': 'Bahasa Malaysia'},
            'dutch': {'code': 'nl', 'name': 'tiếng Hà Lan', 'native': 'Nederlands'},
            'swedish': {'code': 'sv', 'name': 'tiếng Thụy Điển', 'native': 'Svenska'},
            'norwegian': {'code': 'no', 'name': 'tiếng Na Uy', 'native': 'Norsk'},
            'danish': {'code': 'da', 'name': 'tiếng Đan Mạch', 'native': 'Dansk'},
            'polish': {'code': 'pl', 'name': 'tiếng Ba Lan', 'native': 'Polski'},
            'czech': {'code': 'cs', 'name': 'tiếng Séc', 'native': 'Čeština'},
            'hungarian': {'code': 'hu', 'name': 'tiếng Hungary', 'native': 'Magyar'},
            'turkish': {'code': 'tr', 'name': 'tiếng Thổ Nhĩ Kỳ', 'native': 'Türkçe'},
            'greek': {'code': 'el', 'name': 'tiếng Hy Lạp', 'native': 'Ελληνικά'},
            'hebrew': {'code': 'he', 'name': 'tiếng Hebrew', 'native': 'עברית'},
            'finnish': {'code': 'fi', 'name': 'tiếng Phần Lan', 'native': 'Suomi'},
            'ukrainian': {'code': 'uk', 'name': 'tiếng Ukraine', 'native': 'Українська'},
            'bulgarian': {'code': 'bg', 'name': 'tiếng Bulgaria', 'native': 'Български'},
            'romanian': {'code': 'ro', 'name': 'tiếng Romania', 'native': 'Română'},
            'croatian': {'code': 'hr', 'name': 'tiếng Croatia', 'native': 'Hrvatski'},
            'serbian': {'code': 'sr', 'name': 'tiếng Serbia', 'native': 'Српски'},
            'slovenian': {'code': 'sl', 'name': 'tiếng Slovenia', 'native': 'Slovenščina'},
            'slovak': {'code': 'sk', 'name': 'tiếng Slovakia', 'native': 'Slovenčina'},
            'lithuanian': {'code': 'lt', 'name': 'tiếng Lithuania', 'native': 'Lietuvių'},
            'latvian': {'code': 'lv', 'name': 'tiếng Latvia', 'native': 'Latviešu'},
            'estonian': {'code': 'et', 'name': 'tiếng Estonia', 'native': 'Eesti'},
        }
        
        logger.info("✅ Processor initialized successfully")
    
    def _load_whisper_model(self):
        """Load Whisper model with optimizations"""
        try:
            logger.info(f"🔄 Loading Whisper model: {self.model_size}")
            start_time = time.time()
            
            self.model = whisper.load_model(self.model_size)
            
            load_time = time.time() - start_time
            logger.info(f"✅ Whisper model loaded in {load_time:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            raise
    
    def _initialize_gemini_clients(self):
        """Initialize Gemini AI clients"""
        self.gemini_clients = []
        
        for i, api_key in enumerate(self.gemini_api_keys):
            try:
                client = genai.GenerativeModel('gemini-2.5-pro')
                
                self.gemini_clients.append({
                    'client': client,
                    'api_key': api_key,
                    'usage_count': 0,
                    'error_count': 0,
                    'last_used': 0
                })
                
                # Configure API key for this client
                genai.configure(api_key=api_key)
                
                logger.info(f"✅ Gemini client {i+1} initialized: ...{api_key[-8:]}")
                
            except Exception as e:
                logger.error(f"❌ Failed to initialize Gemini client {i+1}: {e}")
        
        logger.info(f"🔑 {len(self.gemini_clients)} Gemini clients ready")
    
    def _exponential_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay"""
        delay = min(self.base_delay * (2 ** attempt) + random.uniform(0, 1), self.max_delay)
        return delay
    
    def _is_timeout_error(self, error: Exception) -> bool:
        """Check if error is a timeout/deadline error"""
        error_msg = str(error).lower()
        timeout_keywords = [
            'timeout', 'deadline exceeded', '504', 'gateway timeout',
            'request timed out', 'deadline', 'too many requests', '429'
        ]
        return any(keyword in error_msg for keyword in timeout_keywords)
    
    def _translate_with_retry(self, client_info: Dict, texts: List[str], 
                             target_language: str, batch_index: int) -> List[str]:
        """
        Translate texts with robust retry mechanism for timeout errors
        """
        lang_info = self.language_mapping.get(target_language.lower())
        if not lang_info:
            logger.warning(f"⚠️ Language not supported: {target_language}")
            return texts
        
        client = client_info['client']
        api_key_short = client_info['api_key'][-8:]
        
        # Configure API key for this request
        genai.configure(api_key=client_info['api_key'])
        
        # Create optimized prompt
        prompt = f"""
You are a professional subtitle translator. Translate these English subtitle segments to {lang_info['name']} ({lang_info['native']}).

CRITICAL REQUIREMENTS:
1. Translate meaning and context, NOT word-by-word
2. Keep similar length to maintain subtitle timing
3. Use natural, conversational language
4. Maintain emotional tone and style
5. Handle technical terms appropriately

SEGMENTS TO TRANSLATE ({len(texts)} items):
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(texts)])}

Return ONLY the translations in the same order, numbered 1-{len(texts)}.
Do not include any explanations or additional text.
"""
        
        # Retry mechanism
        for attempt in range(self.max_retries):
            try:
                logger.info(f"🔄 Batch {batch_index} -> {target_language} (attempt {attempt + 1}/{self.max_retries}) using ...{api_key_short}")
                
                start_time = time.time()
                
                # Make API request
                response = client.generate_content(prompt)
                
                request_time = time.time() - start_time
                
                # Parse response
                translations = self._parse_translation_response(response.text, len(texts))
                
                # Validate translation quality
                if len(translations) == len(texts) and sum(1 for t in translations if t.strip()) >= len(texts) * 0.8:
                    client_info['usage_count'] += 1
                    client_info['last_used'] = time.time()
                    
                    logger.info(f"✅ Batch {batch_index} -> {target_language} completed in {request_time:.2f}s")
                    return translations
                else:
                    logger.warning(f"⚠️ Batch {batch_index} -> {target_language} - Quality check failed (attempt {attempt + 1})")
                    if attempt < self.max_retries - 1:
                        continue
                        
            except Exception as e:
                client_info['error_count'] += 1
                error_msg = str(e)
                
                if self._is_timeout_error(e):
                    if attempt < self.max_retries - 1:
                        delay = self._exponential_backoff(attempt)
                        logger.warning(f"⚠️ Batch {batch_index} timeout error (attempt {attempt + 1}): {error_msg}")
                        logger.info(f"🔄 Retrying after {delay:.1f}s...")
                        time.sleep(delay)
                        continue
                    else:
                        logger.error(f"❌ Batch {batch_index} failed after {self.max_retries} timeout retries")
                else:
                    logger.error(f"❌ Batch {batch_index} non-timeout error: {error_msg}")
                    if attempt < self.max_retries - 1:
                        delay = self._exponential_backoff(attempt)
                        logger.info(f"🔄 Retrying after {delay:.1f}s...")
                        time.sleep(delay)
                        continue
                    break
        
        # If all retries failed, return original texts
        logger.error(f"❌ Batch {batch_index} -> {target_language} failed after all retries, using original texts")
        return texts
    
    def get_file_hash(self, file_path: str) -> str:
        """Generate file hash for caching"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logger.error(f"❌ Error generating file hash: {e}")
            return str(int(time.time()))
    
    def save_to_cache(self, data: Dict, cache_key: str, cache_type: str = 'transcription'):
        """Save data to cache"""
        cache_dir = 'cache'
        os.makedirs(cache_dir, exist_ok=True)
        
        cache_file = os.path.join(cache_dir, f"{cache_key}_{cache_type}.pkl")
        cache_data = {
            'data': data,
            'timestamp': time.time(),
            'model_size': self.model_size
        }
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            logger.info(f"💾 Saved to cache: {cache_type}")
            return True
        except Exception as e:
            logger.error(f"❌ Cache save error: {e}")
            return False
    
    def load_from_cache(self, cache_key: str, cache_type: str = 'transcription') -> Optional[Dict]:
        """Load data from cache"""
        cache_dir = 'cache'
        cache_file = os.path.join(cache_dir, f"{cache_key}_{cache_type}.pkl")
        
        try:
            if not os.path.exists(cache_file):
                return None
            
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            
            # Check cache validity (7 days)
            if time.time() - cache_data.get('timestamp', 0) < 7 * 24 * 3600:
                logger.info(f"🎯 Cache hit: {cache_type}")
                return cache_data['data']
            
            logger.info(f"⚠️ Cache expired: {cache_type}")
            return None
            
        except Exception as e:
            logger.error(f"❌ Cache load error: {e}")
            return None
    
    def extract_audio_and_transcribe(self, video_path: str, output_dir: Optional[str] = None) -> Dict:
        """
        Extract audio and transcribe with caching
        """
        logger.info(f"🎬 Starting transcription: {os.path.basename(video_path)}")
        
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        # Check cache first
        file_hash = self.get_file_hash(video_path)
        cached_result = self.load_from_cache(file_hash, 'transcription')
        
        if cached_result:
            logger.info("🚀 Using cached transcription")
            return cached_result
        
        # Perform transcription
        logger.info(f"🔄 Transcribing with {self.model_size} model...")
        start_time = time.time()
        
        try:
            # Enhanced Whisper parameters
            result = self.model.transcribe(
                video_path,
                word_timestamps=True,
                verbose=False,
                language='en',
                temperature=0.0,
                best_of=3 if self.model_size in ['tiny', 'base'] else 5,
                beam_size=3 if self.model_size in ['tiny', 'base'] else 5,
                patience=1.0,
                fp16=True,  # Use half precision for speed
                compression_ratio_threshold=2.4,
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
            )
            
            transcription_time = time.time() - start_time
            logger.info(f"✅ Transcription completed in {transcription_time:.2f}s")
            logger.info(f"📝 Found {len(result['segments'])} segments")
            
            # Save to cache
            self.save_to_cache(result, file_hash, 'transcription')
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Transcription failed: {e}")
            raise
    
    def translate_with_gemini(self, texts: List[str], target_language: str, context: str = "") -> List[str]:
        """Translate texts using Gemini AI with context (backward compatibility)"""
        if not self.gemini_clients:
            logger.warning("⚠️ No Gemini clients available")
            return texts
        
        # Use first available client
        client_info = self.gemini_clients[0]
        return self._translate_with_retry(client_info, texts, target_language, 1)
    
    def _parse_translation_response(self, response_text: str, expected_count: int) -> List[str]:
        """Parse Gemini response and extract translations"""
        try:
            translations = []
            lines = response_text.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Match numbered lines
                match = re.match(r'^\d+\.\s*(.+)$', line)
                if match:
                    translations.append(match.group(1))
            
            # Ensure correct count
            while len(translations) < expected_count:
                translations.append("")
            
            return translations[:expected_count]
            
        except Exception as e:
            logger.error(f"❌ Error parsing translation: {e}")
            return [""] * expected_count
    
    def parallel_translate_optimized(self, texts: List[str], target_languages: List[str], 
                                   batch_size: int = 20) -> Dict[str, List[str]]:
        """
        Parallel translation using multiple API keys with batching and retry
        """
        if not self.gemini_clients:
            logger.warning("⚠️ No Gemini clients available")
            return {}
        
        logger.info(f"🚀 Starting parallel translation to {len(target_languages)} languages")
        logger.info(f"📊 Batch size: {batch_size}, Total segments: {len(texts)}")
        
        results = {}
        max_workers = min(len(self.gemini_clients), len(target_languages))
        
        def translate_language_batches(client_info, language):
            """Translate all batches for a specific language"""
            try:
                lang_translations = []
                num_batches = (len(texts) + batch_size - 1) // batch_size
                
                for batch_idx in range(num_batches):
                    start_idx = batch_idx * batch_size
                    end_idx = min(start_idx + batch_size, len(texts))
                    batch_texts = texts[start_idx:end_idx]
                    
                    logger.info(f"🔄 Processing batch {batch_idx + 1}/{num_batches} for {language} (segments {start_idx+1}-{end_idx})")
                    
                    # Translate batch with retry mechanism
                    batch_translations = self._translate_with_retry(
                        client_info, batch_texts, language, batch_idx + 1
                    )
                    
                    lang_translations.extend(batch_translations)
                    
                    # Small delay between batches to avoid overwhelming API
                    if batch_idx < num_batches - 1:
                        time.sleep(0.5)
                
                logger.info(f"✅ Completed all batches for {language}")
                return language, lang_translations
                
            except Exception as e:
                logger.error(f"❌ Language translation failed for {language}: {e}")
                return language, texts
        
        # Execute parallel translations
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for i, language in enumerate(target_languages):
                # Assign client in round-robin fashion
                client_info = self.gemini_clients[i % len(self.gemini_clients)]
                future = executor.submit(translate_language_batches, client_info, language)
                futures.append(future)
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(futures):
                try:
                    lang, translated_texts = future.result()
                    results[lang] = translated_texts
                    logger.info(f"📝 Collected results for {lang}")
                except Exception as e:
                    logger.error(f"❌ Failed to get translation result: {e}")
        
        # Log summary
        logger.info(f"🎉 Parallel translation completed")
        for lang, translations in results.items():
            success_rate = sum(1 for t in translations if t.strip()) / len(translations) * 100 if translations else 0
            logger.info(f"📊 {lang}: {len(translations)} segments, {success_rate:.1f}% success rate")
        
        return results
    
    def improve_subtitle_timing(self, segments: List[Dict], 
                               max_chars_per_line: int = 50, 
                               max_duration: float = 6.0,
                               min_duration: float = 1.0) -> List[Dict]:
        """Improve subtitle timing and formatting"""
        logger.info(f"⚙️ Optimizing timing for {len(segments)} segments")
        
        improved_segments = []
        
        for segment in segments:
            text = segment['text'].strip()
            start_time = segment['start']
            end_time = segment['end']
            duration = end_time - start_time
            
            if duration < 0.5 or not text:
                continue
            
            # Ensure minimum duration
            if duration < min_duration:
                end_time = start_time + min_duration
                duration = min_duration
            
            # Clean text
            text = self._clean_subtitle_text(text)
            
            # Handle long segments
            if len(text) > max_chars_per_line or duration > max_duration:
                chunks = self._split_text_intelligently(text, max_chars_per_line)
                
                if len(chunks) > 1:
                    chunk_duration = min(duration / len(chunks), max_duration)
                    
                    for i, chunk in enumerate(chunks):
                        chunk_start = start_time + (i * chunk_duration)
                        chunk_end = min(chunk_start + chunk_duration, end_time)
                        
                        improved_segments.append({
                            'start': chunk_start,
                            'end': chunk_end,
                            'text': chunk.strip()
                        })
                else:
                    improved_segments.append({
                        'start': start_time,
                        'end': min(start_time + max_duration, end_time),
                        'text': text
                    })
            else:
                improved_segments.append({
                    'start': start_time,
                    'end': end_time,
                    'text': text
                })
        
        logger.info(f"✅ Optimized to {len(improved_segments)} segments")
        return improved_segments
    
    def _clean_subtitle_text(self, text: str) -> str:
        """Clean subtitle text"""
        if not text:
            return ""
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Fix punctuation
        text = re.sub(r'\s*([,.!?;:])\s*', r'\1 ', text)
        
        # Remove filler words
        text = re.sub(r'\b(um|uh|er|ah|like|you know)\b', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\[.*?\]', '', text)  # Remove brackets
        text = re.sub(r'\(.*?\)', '', text)  # Remove parentheses
        
        # Clean up
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def _split_text_intelligently(self, text: str, max_chars: int) -> List[str]:
        """Split text intelligently for subtitles"""
        if len(text) <= max_chars:
            return [text]
        
        # Try to split by sentences
        sentences = re.split(r'([.!?]+)', text)
        chunks = []
        current_chunk = ""
        
        i = 0
        while i < len(sentences):
            sentence = sentences[i] if i < len(sentences) else ""
            punctuation = sentences[i+1] if i+1 < len(sentences) else ""
            full_sentence = sentence + punctuation
            
            if len(current_chunk + full_sentence) <= max_chars:
                current_chunk += full_sentence
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = full_sentence
            
            i += 2
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # If still too long, split by words
        final_chunks = []
        for chunk in chunks:
            if len(chunk) > max_chars:
                final_chunks.extend(self._split_by_words(chunk, max_chars))
            else:
                final_chunks.append(chunk)
        
        return [chunk for chunk in final_chunks if chunk.strip()]
    
    def _split_by_words(self, text: str, max_chars: int) -> List[str]:
        """Split text by words"""
        words = text.split()
        chunks = []
        current_chunk = []
        current_length = 0
        
        for word in words:
            word_length = len(word) + 1
            
            if current_length + word_length <= max_chars:
                current_chunk.append(word)
                current_length += word_length
            else:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                current_chunk = [word]
                current_length = len(word)
        
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        
        return chunks
    
    def create_srt_from_segments(self, segments: List[Dict], output_path: str) -> str:
        """Create SRT file from segments"""
        logger.info(f"📝 Creating SRT file: {os.path.basename(output_path)}")
        
        srt_content = []
        
        for i, segment in enumerate(segments, 1):
            start_time = self._seconds_to_srt_time(segment['start'])
            end_time = self._seconds_to_srt_time(segment['end'])
            text = segment['text'].strip()
            
            if not text:
                continue
            
            srt_entry = f"{i}\n{start_time} --> {end_time}\n{text}\n"
            srt_content.append(srt_entry)
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(srt_content))
            
            logger.info(f"✅ Created SRT file with {len(srt_content)} entries")
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Error creating SRT file: {e}")
            raise
    
    def _seconds_to_srt_time(self, seconds: float) -> str:
        """Convert seconds to SRT time format"""
        td = timedelta(seconds=seconds)
        hours = int(td.total_seconds() // 3600)
        minutes = int((td.total_seconds() % 3600) // 60)
        secs = int(td.total_seconds() % 60)
        milliseconds = int((td.total_seconds() % 1) * 1000)
        
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    
    def process_video_complete(self, video_path: str, 
                              target_languages: Optional[List[str]] = None, 
                              output_dir: Optional[str] = None,
                              options: Optional[Dict] = None) -> Dict:
        """Complete video processing pipeline with enhanced retry mechanism"""
        if target_languages is None:
            target_languages = ['vietnamese', 'chinese', 'korean', 'french']
        
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        if options is None:
            options = {}
        
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info("🚀 Starting complete video processing")
        logger.info(f"📁 Input: {os.path.basename(video_path)}")
        logger.info(f"🌐 Languages: {', '.join(target_languages)}")
        
        try:
            # Step 1: Transcription
            logger.info("Step 1: Audio transcription")
            result = self.extract_audio_and_transcribe(video_path, output_dir)
            
            # Step 2: Improve timing
            logger.info("Step 2: Optimizing subtitle timing")
            improved_segments = self.improve_subtitle_timing(
                result['segments'],
                max_chars_per_line=options.get('max_chars', 50),
                max_duration=options.get('max_duration', 6.0)
            )
            
            # Step 3: Create original SRT
            logger.info("Step 3: Creating original subtitle file")
            base_name = Path(video_path).stem
            original_srt_path = os.path.join(output_dir, f"{base_name}_original.srt")
            self.create_srt_from_segments(improved_segments, original_srt_path)
            
            # Step 4: Translation
            translated_files = {}
            if target_languages and self.use_gemini:
                logger.info("Step 4: Starting parallel translation with retry mechanism")
                
                # Extract texts for translation
                texts = [segment['text'] for segment in improved_segments]
                
                # Parallel translation with batching and retry
                batch_size = options.get('batch_size', 20)
                translated_texts_dict = self.parallel_translate_optimized(
                    texts, target_languages, batch_size
                )
                
                # Create SRT files for each language
                for lang, translated_texts in translated_texts_dict.items():
                    if translated_texts and len(translated_texts) == len(improved_segments):
                        # Create translated segments
                        translated_segments = []
                        for segment, translated_text in zip(improved_segments, translated_texts):
                            if translated_text.strip():
                                translated_segments.append({
                                    'start': segment['start'],
                                    'end': segment['end'],
                                    'text': translated_text
                                })
                        
                        # Create SRT file
                        lang_srt_path = os.path.join(output_dir, f"{base_name}_{lang}.srt")
                        self.create_srt_from_segments(translated_segments, lang_srt_path)
                        translated_files[lang] = lang_srt_path
                        
                        logger.info(f"✅ Created {lang} subtitle: {os.path.basename(lang_srt_path)}")
            
            elif target_languages and self.translator:
                # Fallback to sequential translation
                logger.info("Step 4: Sequential translation (fallback)")
                translated_files = self.translate_srt_fallback(
                    original_srt_path, target_languages, output_dir
                )
            
            # Compile results
            results = {
                'original_srt': original_srt_path,
                'translated_files': translated_files,
                'segments_count': len(improved_segments),
                'file_hash': self.get_file_hash(video_path),
                'transcription': result
            }
            
            logger.info("🎉 Video processing completed successfully!")
            logger.info(f"📝 Generated {len(improved_segments)} subtitle segments")
            logger.info(f"🌐 Created {len(translated_files)} translated versions")
            
            # Log API usage statistics
            if self.gemini_clients:
                logger.info("📊 API Usage Statistics:")
                for i, client_info in enumerate(self.gemini_clients):
                    api_short = client_info['api_key'][-8:]
                    usage = client_info['usage_count']
                    errors = client_info['error_count']
                    error_rate = (errors / max(usage + errors, 1)) * 100
                    logger.info(f"   API {i+1} (...{api_short}): {usage} requests, {errors} errors ({error_rate:.1f}% error rate)")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Video processing failed: {e}")
            raise
    
    def translate_srt_fallback(self, srt_path: str, target_languages: List[str], 
                              output_dir: Optional[str] = None) -> Dict[str, str]:
        """Fallback translation using Google Translate"""
        if not self.translator:
            logger.warning("⚠️ No translation service available")
            return {}
        
        if output_dir is None:
            output_dir = os.path.dirname(srt_path)
        
        try:
            import pysrt
        except ImportError:
            logger.error("❌ pysrt not available for fallback translation")
            return {}
        
        # Read original SRT
        try:
            subs = pysrt.open(srt_path, encoding='utf-8')
        except:
            logger.error(f"❌ Cannot read SRT file: {srt_path}")
            return {}
        
        base_name = Path(srt_path).stem.replace('_original', '')
        translated_files = {}
        
        for lang_name in target_languages:
            lang_info = self.language_mapping.get(lang_name.lower())
            if not lang_info:
                logger.warning(f"⚠️ Language not supported: {lang_name}")
                continue
            
            lang_code = lang_info['code']
            logger.info(f"🔄 Translating to {lang_name} (fallback)")
            
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
                    logger.warning(f"⚠️ Translation error for subtitle {sub.index}: {e}")
                    translated_subs.append(sub)  # Keep original
            
            # Save translated file
            output_file = os.path.join(output_dir, f"{base_name}_{lang_name.lower()}.srt")
            try:
                translated_subs.save(output_file, encoding='utf-8')
                translated_files[lang_name] = output_file
                logger.info(f"✅ Created fallback translation: {os.path.basename(output_file)}")
            except Exception as e:
                logger.error(f"❌ Error saving translated file: {e}")
        
        return translated_files


# Enhanced class for WebSocket integration
class OptimizedVideoSubtitleProcessor(VideoSubtitleProcessor):
    """Enhanced processor with WebSocket progress updates and optimization"""
    
    def __init__(self, model_size='base', gemini_api_keys=None, socketio=None):
        # Call parent constructor with multiple API keys
        super().__init__(model_size=model_size, gemini_api_keys=gemini_api_keys)
        self.socketio = socketio
        self.current_task_id = None
        
        logger.info(f"🚀 Initialized OptimizedVideoSubtitleProcessor")
        logger.info(f"🔑 API Keys: {len(self.gemini_api_keys)}")
        logger.info(f"📡 WebSocket: {'Enabled' if socketio else 'Disabled'}")
    
    def set_task_id(self, task_id: str):
        """Set current task ID for progress updates"""
        self.current_task_id = task_id
    
    def emit_progress(self, step: str, progress: int, message: str, **kwargs):
        """Emit progress update via WebSocket"""
        if self.socketio and self.current_task_id:
            data = {
                'task_id': self.current_task_id,
                'step': step,
                'progress': progress,
                'message': message,
                **kwargs
            }
            
            try:
                self.socketio.emit('progress_update', data)
                logger.debug(f"📡 Emitted progress: {step} - {progress}% - {message}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to emit progress: {e}")
    
    def extract_audio_and_transcribe_optimized(self, video_path: str, output_dir: Optional[str] = None, task_id: str = None) -> Dict:
        """Enhanced transcription with WebSocket progress updates"""
        if task_id:
            self.set_task_id(task_id)
        
        self.emit_progress('transcription', 5, f'Initializing transcription with {self.model_size} model...')
        
        # Use parent method with caching
        result = super().extract_audio_and_transcribe(video_path, output_dir)
        
        self.emit_progress('transcription', 60, f'Transcription completed. Found {len(result["segments"])} segments.')
        
        return result
    
    def parallel_translate_enhanced(self, texts: List[str], target_languages: List[str], 
                                  task_id: str = None, batch_size: int = 20) -> Dict[str, List[str]]:
        """Enhanced parallel translation with WebSocket updates"""
        if task_id:
            self.set_task_id(task_id)
        
        self.emit_progress('translation', 70, f'Starting parallel translation to {len(target_languages)} languages...')
        
        # Use parent parallel translation with retry
        results = super().parallel_translate_optimized(texts, target_languages, batch_size)
        
        # Update progress for each completed language
        completed = 0
        total = len(target_languages)
        
        for lang, translations in results.items():
            completed += 1
            progress = 70 + (completed * 25 // total)
            success_rate = sum(1 for t in translations if t.strip()) / len(translations) * 100 if translations else 0
            
            self.emit_progress('translation', progress, 
                             f'Completed {lang} translation ({success_rate:.1f}% success rate)')
        
        return results
    
    def process_video_complete_enhanced(self, video_path: str, target_languages: Optional[List[str]] = None, 
                                      output_dir: Optional[str] = None, options: Optional[Dict] = None,
                                      task_id: str = None) -> Dict:
        """Complete processing with WebSocket progress updates"""
        if task_id:
            self.set_task_id(task_id)
        
        if target_languages is None:
            target_languages = ['vietnamese', 'chinese', 'korean', 'french']
        
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        if options is None:
            options = {}
        
        os.makedirs(output_dir, exist_ok=True)
        
        try:
            # Step 1: Initialize
            self.emit_progress('initialization', 5, 'Initializing enhanced processing...')
            
            # Step 2: Check cache / Transcribe
            file_hash = self.get_file_hash(video_path)
            cached_result = self.load_from_cache(file_hash, 'transcription')
            
            if cached_result:
                self.emit_progress('cache', 50, 'Using cached transcription data...')
                result = cached_result
            else:
                self.emit_progress('transcription', 10, 'Starting audio transcription...')
                result = self.extract_audio_and_transcribe_optimized(video_path, output_dir, task_id)
                self.save_to_cache(result, file_hash, 'transcription')
            
            # Step 3: Improve timing
            self.emit_progress('timing', 65, 'Optimizing subtitle timing...')
            improved_segments = self.improve_subtitle_timing(
                result['segments'],
                max_chars_per_line=options.get('max_chars', 50),
                max_duration=options.get('max_duration', 6.0)
            )
            
            # Step 4: Create original SRT
            self.emit_progress('srt_creation', 68, 'Creating original subtitle file...')
            base_name = Path(video_path).stem
            original_srt_path = os.path.join(output_dir, f"{base_name}_original.srt")
            self.create_srt_from_segments(improved_segments, original_srt_path)
            
            # Step 5: Translation
            translated_files = {}
            if target_languages and self.use_gemini:
                texts = [segment['text'] for segment in improved_segments]
                batch_size = options.get('batch_size', 20)
                
                translated_texts_dict = self.parallel_translate_enhanced(
                    texts, target_languages, task_id, batch_size
                )
                
                # Create SRT files
                for lang, translated_texts in translated_texts_dict.items():
                    if translated_texts and len(translated_texts) == len(improved_segments):
                        translated_segments = []
                        for segment, translated_text in zip(improved_segments, translated_texts):
                            if translated_text.strip():
                                translated_segments.append({
                                    'start': segment['start'],
                                    'end': segment['end'],
                                    'text': translated_text
                                })
                        
                        lang_srt_path = os.path.join(output_dir, f"{base_name}_{lang}.srt")
                        self.create_srt_from_segments(translated_segments, lang_srt_path)
                        translated_files[lang] = lang_srt_path
            
            # Step 6: Complete
            self.emit_progress('completion', 100, 'Processing completed successfully!')
            
            results = {
                'original_srt': original_srt_path,
                'translated_files': translated_files,
                'segments_count': len(improved_segments),
                'file_hash': file_hash,
                'transcription': result
            }
            
            logger.info("🎉 Enhanced video processing completed!")
            return results
            
        except Exception as e:
            self.emit_progress('error', 0, f'Error: {str(e)}')
            logger.error(f"❌ Enhanced processing failed: {e}")
            raise


def main():
    """Command line interface with enhanced error handling"""
    parser = argparse.ArgumentParser(description='Enhanced AI Video Subtitle Generator with Retry Mechanism')
    parser.add_argument('video_path', help='Path to video file')
    parser.add_argument('--output-dir', help='Output directory (default: same as video)')
    parser.add_argument('--languages', nargs='+', 
                       default=['vietnamese', 'chinese', 'korean', 'french'],
                       help='Target languages for translation')
    parser.add_argument('--model', default='base', 
                       choices=['tiny', 'base', 'small', 'medium', 'large'],
                       help='Whisper model size')
    parser.add_argument('--api-keys', nargs='+',
                       help='Gemini API keys for parallel translation')
    parser.add_argument('--api-key', 
                       help='Single Gemini API key (backward compatibility)')
    parser.add_argument('--max-chars', type=int, default=50,
                       help='Maximum characters per subtitle line')
    parser.add_argument('--max-duration', type=float, default=6.0,
                       help='Maximum subtitle duration in seconds')
    parser.add_argument('--batch-size', type=int, default=20,
                       help='Batch size for translation requests')
    parser.add_argument('--max-retries', type=int, default=5,
                       help='Maximum number of retries for failed requests')
    parser.add_argument('--timeout', type=int, default=60,
                       help='Request timeout in seconds')
    
    args = parser.parse_args()
    
    # Handle API keys
    api_keys = None
    if args.api_keys:
        api_keys = args.api_keys
    elif args.api_key:
        api_keys = [args.api_key]
    
    if not api_keys:
        logger.warning("⚠️ No API keys provided. Translation will be limited to fallback methods.")
    
    # Initialize processor
    processor = VideoSubtitleProcessor(
        model_size=args.model,
        gemini_api_keys=api_keys
    )
    
    # Update retry settings
    if hasattr(processor, 'max_retries'):
        processor.max_retries = args.max_retries
        processor.timeout_seconds = args.timeout
        logger.info(f"🔄 Updated retry settings: {args.max_retries} max retries, {args.timeout}s timeout")
    
    # Process video
    options = {
        'max_chars': args.max_chars,
        'max_duration': args.max_duration,
        'batch_size': args.batch_size
    }
    
    try:
        logger.info("🎬 Starting video processing...")
        results = processor.process_video_complete(
            video_path=args.video_path,
            target_languages=args.languages,
            output_dir=args.output_dir,
            options=options
        )
        
        print("\n" + "="*80)
        print("🎉 PROCESSING COMPLETED SUCCESSFULLY!")
        print("="*80)
        print(f"📁 Original subtitle: {results['original_srt']}")
        
        if results['translated_files']:
            print(f"🌐 Translated files:")
            for lang, file_path in results['translated_files'].items():
                print(f"  - {lang.capitalize()}: {file_path}")
        else:
            print("⚠️ No translations created (check API keys and logs)")
        
        print(f"📊 Total segments: {results['segments_count']}")
        
        # Show success statistics
        if processor.gemini_clients:
            print(f"\n📈 API Usage Summary:")
            total_requests = sum(client['usage_count'] for client in processor.gemini_clients)
            total_errors = sum(client['error_count'] for client in processor.gemini_clients)
            overall_success_rate = ((total_requests) / max(total_requests + total_errors, 1)) * 100
            print(f"   Total successful requests: {total_requests}")
            print(f"   Total errors: {total_errors}")
            print(f"   Overall success rate: {overall_success_rate:.1f}%")
        
    except KeyboardInterrupt:
        print("\n❌ Processing interrupted by user")
        logger.info("Processing interrupted by user")
    except Exception as e:
        print(f"\n❌ Processing failed: {e}")
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()