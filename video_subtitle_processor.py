# video_subtitle_processor.py

from faster_whisper import WhisperModel
import os
import re
import time
import hashlib
import pickle
from datetime import timedelta
from pathlib import Path
import argparse
import logging
from typing import List, Dict, Optional
import concurrent.futures

# Import the enhanced translation manager
from enhanced_translation_manager import EnhancedTranslationManager

# Enhanced logging setup for Docker visibility
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # This will show in Docker logs
    ]
)
logger = logging.getLogger(__name__)

class VideoSubtitleProcessor:
    """
    Enhanced Video Subtitle Processor with intelligent translation management:
    - Smart API key switching when limits reached
    - Automatic fallback to Google Translate
    - Robust retry mechanism for API timeouts
    - Performance monitoring
    - Docker logs integration
    """
    
    def __init__(self, model_size='base', gemini_api_key=None, gemini_api_keys=None, socketio=None):
        """
        Initialize processor
        
        Args:
            model_size: Whisper model size
            gemini_api_key: Single API key (backward compatibility)
            gemini_api_keys: List of API keys for intelligent switching
        """
        self.model_size = model_size
        
        # Handle both single and multiple API keys
        api_keys = []
        if gemini_api_keys:
            api_keys = gemini_api_keys
        elif gemini_api_key:
            api_keys = [gemini_api_key]
        
        # Initialize enhanced translation manager
        self.translation_manager = EnhancedTranslationManager(api_keys, socketio=socketio)
        
        # For backward compatibility
        self.use_gemini = len(api_keys) > 0
        
        # Retry configuration
        self.max_retries = 3
        self.base_delay = 1.0
        self.max_delay = 30.0
        self.timeout_seconds = 60  # Request timeout
        
        logger.info(f"🚀 Initializing Enhanced Video Subtitle Processor")
        logger.info(f"📊 Model: {model_size}")
        logger.info(f"🔑 API Keys: {len(api_keys)}")
        logger.info(f"🔄 Max Retries: {self.max_retries}")
        
        # Load Whisper model
        self._load_whisper_model()
        
        # Language mapping (kept for compatibility)
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
        
        logger.info("✅ Enhanced processor initialized successfully")
    
    def _load_whisper_model(self):
        """Load Whisper model with optimizations"""
        try:
            logger.info(f"🔄 Loading Whisper model: {self.model_size}")
            start_time = time.time()
            
            self.model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
            
            load_time = time.time() - start_time
            logger.info(f"✅ Whisper model loaded in {load_time:.2f}s")
            
        except Exception as e:
            logger.error(f"❌ Failed to load Whisper model: {e}")
            raise
    
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
            segments_generator, info = self.model.transcribe(
                video_path,
                word_timestamps=True,
                language='en',
                best_of=3 if self.model_size in ['tiny', 'base'] else 5,
                beam_size=3 if self.model_size in ['tiny', 'base'] else 5,
                # patience=1.0,
                # compression_ratio_threshold=2.4,
                # logprob_threshold=-1.0,
                # no_speech_threshold=0.6,
            )
            segments = []
            for segment in segments_generator:
                segments.append({
                    'start': segment.start,
                    'end': segment.end,
                    'text': segment.text,
                    'words': segment.words if hasattr(segment, 'words') else None
                })
            
            # Trả về kết quả dưới dạng Dict để tương thích với phần code còn lại
            result = {
                'segments': segments,
                'info': info  # Giữ lại thông tin như ngôn ngữ được detect, v.v.
            }

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
        """Translate texts using enhanced translation manager (backward compatibility)"""
        return self.translation_manager.translate_texts(texts, target_language, context)
    
    def parallel_translate_optimized(self, texts: List[str], target_languages: List[str], 
                                   batch_size: int = 20) -> Dict[str, List[str]]:
        """
        Enhanced parallel translation with intelligent API switching and fallback
        """
        logger.info(f"🚀 Starting enhanced parallel translation to {len(target_languages)} languages")
        logger.info(f"📊 Total segments: {len(texts)}, Available API keys: {len(self.translation_manager.gemini_keys)}")
        
        results = {}
        
        # Use thread pool for parallel processing
        max_workers = min(4, len(target_languages))  # Reasonable concurrency limit
        
        def translate_language(language):
            """Translate all texts for a specific language"""
            try:
                logger.info(f"🌐 Starting translation to {language}")
                translations = self.translation_manager.translate_texts(texts, language)
                logger.info(f"✅ Completed translation to {language}")
                return language, translations
            except Exception as e:
                logger.error(f"❌ Translation failed for {language}: {e}")
                return language, texts  # Return originals on failure
        
        # Execute translations in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all translation tasks
            futures = {executor.submit(translate_language, lang): lang for lang in target_languages}
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(futures):
                try:
                    lang, translated_texts = future.result(timeout=300)  # 5 minute timeout per language
                    results[lang] = translated_texts
                    
                    # Calculate success rate
                    success_rate = sum(1 for t in translated_texts if t.strip()) / len(translated_texts) * 100 if translated_texts else 0
                    logger.info(f"📝 {lang}: {len(translated_texts)} segments, {success_rate:.1f}% success rate")
                    
                except concurrent.futures.TimeoutError:
                    lang = futures[future]
                    logger.error(f"❌ Translation timeout for {lang}")
                    results[lang] = texts  # Fallback to originals
                except Exception as e:
                    lang = futures[future]
                    logger.error(f"❌ Translation error for {lang}: {e}")
                    results[lang] = texts  # Fallback to originals
        
        # Log API status after translation
        api_status = self.translation_manager.get_api_status()
        logger.info("📊 Final API Status:")
        for key_info in api_status['gemini_keys']:
            logger.info(f"   {key_info['key']}: {key_info['status']}, Usage: {key_info['usage_count']}, Errors: {key_info['error_count']}")
        
        if api_status['google_translate']:
            logger.info("   Google Translate: Available as fallback")
        
        logger.info(f"🎉 Enhanced parallel translation completed for {len(results)} languages")
        return results
    
    def improve_subtitle_timing(self, segments: List[Dict], 
                               max_chars_per_line: int = 50, 
                               max_duration: float = 6.0,
                               min_duration: float = 1.0,
                               allow_split: bool = True) -> List[Dict]:
        """Improve subtitle timing and formatting"""
        logger.info(f"⚙️ Optimizing timing for {len(segments)} segments")
        
        improved_segments = []
        
        # Step 0: Split long segments into sentences using word timestamps
        segments = self._split_segments_by_sentences(segments)
        
        # Step 0: Merge fragments intelligently to form complete sentences first
        segments = self._merge_fragments(segments, max_chars_per_line)
        
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
            
            # Allow complete sentences to exceed max_chars slightly (20%) to avoid unnecessary splitting
            is_complete_sentence = text[-1] in '.!?' if text else False
            limit_tolerance = 1.2 if is_complete_sentence else 1.0
            
            # Handle 0 as unlimited (infinite)
            effective_char_limit = (max_chars_per_line * limit_tolerance) if max_chars_per_line > 0 else float('inf')
            effective_max_duration = max_duration if max_duration > 0 else float('inf')
            
            # Handle long segments
            # Only split if limits are enabled (>0) and exceeded
            exceeds_chars = max_chars_per_line > 0 and len(text) > effective_char_limit
            exceeds_duration = max_duration > 0 and duration > effective_max_duration
            
            if allow_split and (exceeds_chars or exceeds_duration):
                # Only split text if it actually exceeds the effective limit
                if exceeds_chars:
                    chunks = self._split_text_intelligently(text, max_chars_per_line)
                else:
                    # If here only because of duration, keep text intact
                    chunks = [text]
                
                if len(chunks) > 1:
                    chunk_duration = duration / len(chunks)
                    
                    for i, chunk in enumerate(chunks):
                        chunk_start = start_time + (i * chunk_duration)
                        chunk_end = min(chunk_start + chunk_duration, end_time)
                        
                        improved_segments.append({
                            'start': chunk_start,
                            'end': chunk_end,
                            'text': chunk.strip()
                        })
                else:
                    final_end = end_time
                    # Only cap duration if max_duration is set (>0) and text is short enough
                    if max_duration > 0 and (max_chars_per_line <= 0 or len(text) <= max_chars_per_line):
                        final_end = min(start_time + max_duration, end_time)
                    
                    improved_segments.append({
                        'start': start_time,
                        'end': final_end,
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

    def _merge_fragments(self, segments: List[Dict], max_chars: int, max_gap: float = 2.0) -> List[Dict]:
        """
        Merge short segments that are likely parts of the same sentence.
        Logic: If a segment doesn't end with punctuation, try to merge with next.
        """
        if not segments:
            return []
        
        merged = []
        current = segments[0]
        
        # Treat 0 as unlimited for merging purposes
        limit = float('inf') if max_chars <= 0 else max_chars
        
        for next_seg in segments[1:]:
            text = current['text'].strip()
            next_text = next_seg['text'].strip()
            
            if not text:
                current = next_seg
                continue
                
            # Check if current segment ends with sentence punctuation
            is_sentence_end = text[-1] in '.!?' if text else False
            
            gap = next_seg['start'] - current['end']
            combined_len = len(text) + 1 + len(next_text)
            
            should_merge = False
            
            # Only merge if gap is reasonable (not a long silence)
            if gap < max_gap:
                # Case 1: Not a sentence end -> Merge to complete the sentence (allow slightly over max_chars)
                if not is_sentence_end and combined_len <= limit * 1.2:
                    should_merge = True
                # Case 2: Is a sentence end, but both parts are very short -> Merge to fill the line
                elif is_sentence_end and combined_len <= limit and len(text) < 15:
                    should_merge = True
            
            if should_merge:
                current['end'] = next_seg['end']
                current['text'] = text + " " + next_text
            else:
                merged.append(current)
                current = next_seg
                
        merged.append(current)
        return merged

    def _split_segments_by_sentences(self, segments: List[Dict]) -> List[Dict]:
        """
        Split segments containing multiple sentences into individual sentence segments
        using word timestamps.
        """
        # Common abbreviations that end with a dot but aren't sentence ends
        abbreviations = {
            'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.', 'vs.', 'no.', 'fig.', 'st.', 'co.', 'ltd.', 'inc.',
            'u.s.', 'u.k.', 'e.g.', 'i.e.', 'etc.'
        }
        
        new_segments = []
        for seg in segments:
            # Fallback: If no words info, use text-based splitting with interpolation
            if not seg.get('words'):
                text = seg['text'].strip()
                # Split by sentence endings, keeping the punctuation
                # Regex: Split after .!? followed by space and uppercase letter/number
                sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9])', text)
                
                if len(sentences) > 1:
                    duration = seg['end'] - seg['start']
                    total_chars = len(text)
                    current_start = seg['start']
                    
                    for sentence in sentences:
                        # Estimate duration based on character count
                        sent_duration = duration * (len(sentence) / total_chars)
                        new_segments.append({
                            'start': current_start,
                            'end': current_start + sent_duration,
                            'text': sentence,
                            'words': None
                        })
                        current_start += sent_duration
                else:
                    new_segments.append(seg)
                continue
                
            words = seg['words']
            current_words = []
            
            for i, word in enumerate(words):
                current_words.append(word)
                w_text = word.word.strip()
                w_lower = w_text.lower()
                
                # Check for sentence endings
                is_end_char = w_text and (w_text[-1] in '.!?' or (len(w_text) > 1 and w_text[-2] in '.!?' and w_text[-1] in '"\''))
                
                # Check if it's an abbreviation
                is_abbrev = w_lower in abbreviations
                
                # Heuristic: Check next word to confirm sentence boundary
                is_real_end = is_end_char and not is_abbrev
                
                if is_real_end and i + 1 < len(words):
                    next_word = words[i+1].word.strip()
                    # If next word starts with lowercase, it's likely not a sentence end (e.g. "end. but")
                    if next_word and next_word[0].islower():
                        is_real_end = False

                if is_real_end:
                    # Found a sentence boundary
                    if current_words:
                        # Reconstruct text from words
                        text = "".join([w.word for w in current_words]).strip()
                        
                        new_segments.append({
                            'start': current_words[0].start,
                            'end': current_words[-1].end,
                            'text': text,
                            'words': current_words
                        })
                        current_words = []
            
            # Append any remaining words
            if current_words:
                text = "".join([w.word for w in current_words]).strip()
                new_segments.append({
                    'start': current_words[0].start,
                    'end': current_words[-1].end,
                    'text': text,
                    'words': current_words
                })
                
        return new_segments

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
        """Complete video processing pipeline with enhanced translation management"""
        if target_languages is None:
            target_languages = ['vietnamese', 'chinese', 'korean', 'french']
        
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        if options is None:
            options = {}
        
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info("🚀 Starting complete video processing with enhanced translation")
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
            
            # Step 4: Enhanced Translation
            translated_files = {}
            if target_languages and self.use_gemini:
                logger.info("Step 4: Starting enhanced parallel translation with intelligent API management")
                
                # Extract texts for translation
                texts = [segment['text'] for segment in improved_segments]
                
                # Enhanced parallel translation with intelligent switching
                batch_size = options.get('batch_size', 15)  # Smaller batches for reliability
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
            
            # Compile results
            results = {
                'original_srt': original_srt_path,
                'translated_files': translated_files,
                'segments_count': len(improved_segments),
                'file_hash': self.get_file_hash(video_path),
                'transcription': result,
                'api_status': self.translation_manager.get_api_status()
            }
            
            logger.info("🎉 Enhanced video processing completed successfully!")
            logger.info(f"📝 Generated {len(improved_segments)} subtitle segments")
            logger.info(f"🌐 Created {len(translated_files)} translated versions")
            
            # Log final API usage statistics
            api_status = results['api_status']
            logger.info("📊 Final API Usage Statistics:")
            logger.info(f"   Total Gemini requests: {api_status['total_usage']}")
            logger.info(f"   Total Gemini errors: {api_status['total_errors']}")
            logger.info(f"   Google Translate available: {api_status['google_translate']}")
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Enhanced video processing failed: {e}")
            raise
    
    def get_api_status(self) -> Dict:
        """Get current API status"""
        return self.translation_manager.get_api_status()
    
    def reset_api_errors(self):
        """Reset API key error states"""
        return self.translation_manager.reset_key_errors()


# Enhanced class for WebSocket integration
class OptimizedVideoSubtitleProcessor(VideoSubtitleProcessor):
    """Enhanced processor with WebSocket progress updates and optimization"""
    
    def __init__(self, model_size='base', gemini_api_keys=None, socketio=None):
        # Call parent constructor with multiple API keys
        super().__init__(model_size=model_size, gemini_api_keys=gemini_api_keys, socketio=socketio)
        self.socketio = socketio
        self.current_task_id = None
        
        logger.info(f"🚀 Initialized OptimizedVideoSubtitleProcessor with enhanced translation")
        logger.info(f"🔑 API Keys: {len(gemini_api_keys or [])}")
        logger.info(f"📡 WebSocket: {'Enabled' if socketio else 'Disabled'}")
    
    def set_task_id(self, task_id: str):
        """Set current task ID for progress updates"""
        self.current_task_id = task_id
        # IMPORTANT: Also set task_id in translation_manager
        if self.translation_manager:
            self.translation_manager.set_task_id(task_id)
    
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
                self.socketio.sleep(0.1)
                logger.debug(f"📡 Emitted progress: {step} - {progress}% - {message}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to emit progress: {e}")


def main():
    """Command line interface with enhanced translation management"""
    parser = argparse.ArgumentParser(description='Enhanced AI Video Subtitle Generator with Intelligent Translation')
    parser.add_argument('video_path', help='Path to video file')
    parser.add_argument('--output-dir', help='Output directory (default: same as video)')
    parser.add_argument('--languages', nargs='+', 
                       default=['vietnamese', 'chinese', 'korean', 'french'],
                       help='Target languages for translation')
    parser.add_argument('--model', default='base', 
                       choices=['tiny', 'base', 'small', 'medium', 'large'],
                       help='Whisper model size')
    parser.add_argument('--api-keys', nargs='+',
                       help='Gemini API keys for intelligent translation management')
    parser.add_argument('--max-chars', type=int, default=50,
                       help='Maximum characters per subtitle line')
    parser.add_argument('--max-duration', type=float, default=6.0,
                       help='Maximum subtitle duration in seconds')
    parser.add_argument('--batch-size', type=int, default=15,
                       help='Batch size for translation requests')
    parser.add_argument('--reset-api-errors', action='store_true',
                       help='Reset API key error states before processing')
    
    args = parser.parse_args()
    
    if not args.api_keys:
        logger.warning("⚠️ No API keys provided. Translation will be limited to fallback methods.")
    
    # Initialize processor
    processor = VideoSubtitleProcessor(
        model_size=args.model,
        gemini_api_keys=args.api_keys
    )
    
    # Reset API errors if requested
    if args.reset_api_errors:
        reset_count = processor.reset_api_errors()
        logger.info(f"🔄 Reset {reset_count} API key error states")
    
    # Process video
    options = {
        'max_chars': args.max_chars,
        'max_duration': args.max_duration,
        'batch_size': args.batch_size
    }
    
    try:
        logger.info("🎬 Starting enhanced video processing...")
        results = processor.process_video_complete(
            video_path=args.video_path,
            target_languages=args.languages,
            output_dir=args.output_dir,
            options=options
        )
        
        print("\n" + "="*80)
        print("🎉 ENHANCED PROCESSING COMPLETED SUCCESSFULLY!")
        print("="*80)
        print(f"📁 Original subtitle: {results['original_srt']}")
        
        if results['translated_files']:
            print(f"🌐 Translated files:")
            for lang, file_path in results['translated_files'].items():
                print(f"  - {lang.capitalize()}: {file_path}")
        else:
            print("⚠️ No translations created")
        
        print(f"📊 Total segments: {results['segments_count']}")
        
        # Show enhanced API statistics
        api_status = results['api_status']
        if api_status['gemini_keys']:
            print(f"\n📈 Enhanced API Management Summary:")
            print(f"   Total Gemini requests: {api_status['total_usage']}")
            print(f"   Total Gemini errors: {api_status['total_errors']}")
            print(f"   Google Translate fallback: {'Available' if api_status['google_translate'] else 'Unavailable'}")
            
            print(f"\n🔑 API Key Status:")
            for key_info in api_status['gemini_keys']:
                status_emoji = {
                    'active': '✅',
                    'rate_limited': '⚠️',
                    'quota_exceeded': '❌',
                    'error': '🔄',
                    'cooling_down': '⏳'
                }.get(key_info['status'], '❓')
                
                print(f"   {status_emoji} {key_info['key']}: {key_info['status']} "
                      f"(Used: {key_info['usage_count']}, Errors: {key_info['error_count']})")
        
    except KeyboardInterrupt:
        print("\n❌ Processing interrupted by user")
        logger.info("Processing interrupted by user")
    except Exception as e:
        print(f"\n❌ Processing failed: {e}")
        logger.error(f"Processing failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()