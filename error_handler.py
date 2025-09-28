import whisper
import os
import re
import time
import asyncio
import concurrent.futures
from datetime import timedelta
from pathlib import Path
import argparse
import logging
import google.generativeai as genai
from typing import List, Dict, Optional, Tuple
import threading
from queue import Queue
import psutil
import hashlib
import pickle
import json
from flask import Flask, request, jsonify, render_template_string, send_file
from werkzeug.utils import secure_filename
import random
from dataclasses import dataclass
import backoff

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/processor.log') if os.path.exists('logs') else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class APIKeyInfo:
    """API Key information with usage tracking"""
    key: str
    usage_count: int = 0
    error_count: int = 0
    last_used: float = 0
    consecutive_errors: int = 0
    is_valid: bool = True
    avg_response_time: float = 0
    
    @property
    def short_key(self):
        return f"...{self.key[-8:]}"

class EnhancedRetryHandler:
    """Enhanced retry handler with exponential backoff and circuit breaker pattern"""
    
    def __init__(self, max_retries=5, base_delay=1, max_delay=60):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def should_retry(self, exception, attempt):
        """Determine if we should retry based on exception type and attempt count"""
        if attempt >= self.max_retries:
            return False
        
        retry_exceptions = [
            "504",  # Gateway timeout
            "503",  # Service unavailable
            "502",  # Bad gateway
            "429",  # Too many requests
            "timeout",
            "deadline",
            "temporarily unavailable"
        ]
        
        error_msg = str(exception).lower()
        return any(retry_error in error_msg for retry_error in retry_exceptions)
    
    def get_delay(self, attempt):
        """Calculate delay with exponential backoff and jitter"""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        # Add jitter to prevent thundering herd
        jitter = random.uniform(0.1, 0.3) * delay
        return delay + jitter

class OptimizedVideoSubtitleProcessor:
    """
    Enhanced Video Subtitle Processor with robust error handling and API key management
    """
    
    def __init__(self, model_size='base', gemini_api_keys=None, cache_dir='cache'):
        self.model_size = model_size
        self.api_keys = []
        self.cache_dir = cache_dir
        self.retry_handler = EnhancedRetryHandler()
        
        # Performance tracking
        self.performance_stats = {
            'transcription_time': 0,
            'translation_time': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'successful_translations': 0,
            'failed_translations': 0,
            'retries_performed': 0
        }
        
        logger.info(f"Initializing Enhanced Video Subtitle Processor")
        logger.info(f"Model: {model_size}, Cache: {cache_dir}")
        
        # Initialize with API keys if provided
        if gemini_api_keys:
            self.add_api_keys(gemini_api_keys)
        
        # Initialize Whisper model
        self._load_whisper_model()
        
        # Create cache directory
        os.makedirs(cache_dir, exist_ok=True)
        
        # Enhanced language mapping
        self.language_mapping = {
            'vietnamese': {'code': 'vi', 'name': 'tiếng Việt', 'native': 'Tiếng Việt', 'flag': '🇻🇳'},
            'chinese': {'code': 'zh-cn', 'name': 'tiếng Trung', 'native': '中文 (简体)', 'flag': '🇨🇳'},
            'chinese_traditional': {'code': 'zh-tw', 'name': 'tiếng Trung (phồn thể)', 'native': '中文 (繁體)', 'flag': '🇹🇼'},
            'korean': {'code': 'ko', 'name': 'tiếng Hàn', 'native': '한국어', 'flag': '🇰🇷'},
            'japanese': {'code': 'ja', 'name': 'tiếng Nhật', 'native': '日本語', 'flag': '🇯🇵'},
            'french': {'code': 'fr', 'name': 'tiếng Pháp', 'native': 'Français', 'flag': '🇫🇷'},
            'spanish': {'code': 'es', 'name': 'tiếng Tây Ban Nha', 'native': 'Español', 'flag': '🇪🇸'},
            'german': {'code': 'de', 'name': 'tiếng Đức', 'native': 'Deutsch', 'flag': '🇩🇪'},
            'italian': {'code': 'it', 'name': 'tiếng Ý', 'native': 'Italiano', 'flag': '🇮🇹'},
            'portuguese': {'code': 'pt', 'name': 'tiếng Bồ Đào Nha', 'native': 'Português', 'flag': '🇵🇹'},
            'russian': {'code': 'ru', 'name': 'tiếng Nga', 'native': 'Русский', 'flag': '🇷🇺'},
            'arabic': {'code': 'ar', 'name': 'tiếng Ả Rập', 'native': 'العربية', 'flag': '🇸🇦'},
            'thai': {'code': 'th', 'name': 'tiếng Thái', 'native': 'ไทย', 'flag': '🇹🇭'},
            'hindi': {'code': 'hi', 'name': 'tiếng Hindi', 'native': 'हिन्दी', 'flag': '🇮🇳'},
        }
    
    def add_api_keys(self, api_keys):
        """Add API keys and validate them"""
        if isinstance(api_keys, str):
            api_keys = [key.strip() for key in api_keys.split('\n') if key.strip()]
        
        for key in api_keys:
            if key and key not in [api_key.key for api_key in self.api_keys]:
                api_key_info = APIKeyInfo(key=key)
                self.api_keys.append(api_key_info)
                logger.info(f"Added API key: {api_key_info.short_key}")
    
    def validate_api_keys(self):
        """Validate all API keys"""
        validation_results = {}
        
        for api_key_info in self.api_keys:
            try:
                # Configure Gemini with this key
                genai.configure(api_key=api_key_info.key)
                model = genai.GenerativeModel('gemini-pro')
                
                # Test with a simple request
                response = model.generate_content("Hello, please respond with 'OK'")
                
                if response and response.text:
                    api_key_info.is_valid = True
                    validation_results[api_key_info.key] = 'valid'
                    logger.info(f"API key validation successful: {api_key_info.short_key}")
                else:
                    api_key_info.is_valid = False
                    validation_results[api_key_info.key] = 'invalid'
                    
            except Exception as e:
                api_key_info.is_valid = False
                validation_results[api_key_info.key] = 'invalid'
                logger.error(f"API key validation failed for {api_key_info.short_key}: {e}")
        
        valid_count = sum(1 for result in validation_results.values() if result == 'valid')
        invalid_count = len(validation_results) - valid_count
        
        return {
            'results': validation_results,
            'valid': valid_count,
            'invalid': invalid_count
        }
    
    def get_available_api_key(self):
        """Get next available API key using round-robin with health checking"""
        valid_keys = [key for key in self.api_keys if key.is_valid and key.consecutive_errors < 3]
        
        if not valid_keys:
            # Reset consecutive errors if all keys are marked as bad
            for key in self.api_keys:
                key.consecutive_errors = 0
            valid_keys = [key for key in self.api_keys if key.is_valid]
        
        if not valid_keys:
            raise Exception("No valid API keys available")
        
        # Sort by last used time and error count
        valid_keys.sort(key=lambda x: (x.consecutive_errors, x.last_used))
        selected_key = valid_keys[0]
        selected_key.last_used = time.time()
        
        return selected_key
    
    def _load_whisper_model(self):
        """Load Whisper model with optimizations"""
        try:
            logger.info(f"Loading Whisper model: {self.model_size}")
            start_time = time.time()
            
            self.model = whisper.load_model(
                self.model_size,
                download_root=os.path.expanduser("~/.cache/whisper")
            )
            
            load_time = time.time() - start_time
            logger.info(f"Whisper model loaded in {load_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    
    def translate_with_retry(self, texts, target_language, batch_id=0):
        """Translate texts with robust retry mechanism"""
        lang_info = self.language_mapping.get(target_language.lower())
        if not lang_info:
            logger.warning(f"Language not supported: {target_language}")
            return texts
        
        for attempt in range(self.retry_handler.max_retries):
            api_key_info = None
            try:
                # Get available API key
                api_key_info = self.get_available_api_key()
                
                # Configure Gemini
                genai.configure(api_key=api_key_info.key)
                model = genai.GenerativeModel('gemini-pro')
                
                logger.info(f"Translating batch {batch_id} to {target_language} "
                           f"(attempt {attempt + 1}) using {api_key_info.short_key}")
                
                # Create translation prompt
                prompt = f"""
You are a professional subtitle translator. Translate these English subtitle segments to {lang_info['name']} ({lang_info['native']}).

REQUIREMENTS:
1. Translate meaning and context naturally
2. Keep similar length for subtitle timing
3. Use conversational language
4. Maintain emotional tone
5. Ensure cultural appropriateness

SEGMENTS ({len(texts)} items):
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(texts)])}

Return ONLY the translations in the same order, numbered 1-{len(texts)}.
"""
                
                # Make request with timeout
                start_time = time.time()
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        max_output_tokens=2048,
                    )
                )
                
                request_time = time.time() - start_time
                
                if not response or not response.text:
                    raise Exception("Empty response from Gemini")
                
                # Parse response
                translations = self._parse_translation_response(response.text, len(texts))
                
                if len(translations) != len(texts):
                    raise Exception(f"Translation count mismatch: expected {len(texts)}, got {len(translations)}")
                
                # Update API key stats on success
                api_key_info.usage_count += 1
                api_key_info.consecutive_errors = 0
                api_key_info.avg_response_time = (
                    (api_key_info.avg_response_time * (api_key_info.usage_count - 1) + request_time) 
                    / api_key_info.usage_count
                )
                
                self.performance_stats['successful_translations'] += 1
                self.performance_stats['api_calls'] += 1
                
                logger.info(f"Successfully translated batch {batch_id} to {target_language} "
                           f"in {request_time:.2f}s")
                
                return translations
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Update API key error stats
                if api_key_info:
                    api_key_info.error_count += 1
                    api_key_info.consecutive_errors += 1
                
                self.performance_stats['failed_translations'] += 1
                
                # Check if we should retry
                if self.retry_handler.should_retry(e, attempt):
                    delay = self.retry_handler.get_delay(attempt)
                    logger.warning(f"Translation attempt {attempt + 1} failed for batch {batch_id}: {e}")
                    logger.info(f"Retrying in {delay:.2f}s...")
                    
                    self.performance_stats['retries_performed'] += 1
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Translation failed for batch {batch_id} after {attempt + 1} attempts: {e}")
                    break
        
        # Return original texts as fallback
        logger.warning(f"Using fallback for batch {batch_id} - returning original texts")
        return texts
    
    def parallel_translate_optimized(self, texts, target_languages, progress_callback=None):
        """Enhanced parallel translation with robust error handling"""
        if not self.api_keys:
            logger.warning("No API keys available for translation")
            return {}
        
        logger.info(f"Starting parallel translation to {len(target_languages)} languages")
        logger.info(f"Using {len([k for k in self.api_keys if k.is_valid])} valid API keys")
        
        start_time = time.time()
        results = {}
        
        # Calculate optimal batch size (split texts into batches for better error handling)
        batch_size = max(1, len(texts) // 4)  # Split into 4 batches
        text_batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
        
        def translate_language(language, language_index):
            """Translate all text batches for a specific language"""
            try:
                language_results = []
                
                for batch_index, text_batch in enumerate(text_batches):
                    batch_id = f"{language}-{batch_index}"
                    translated_batch = self.translate_with_retry(
                        text_batch, language, batch_id
                    )
                    language_results.extend(translated_batch)
                    
                    # Update progress
                    if progress_callback:
                        overall_progress = 75 + (
                            (language_index * len(text_batches) + batch_index + 1) * 20
                        ) // (len(target_languages) * len(text_batches))
                        
                        progress_callback(
                            overall_progress,
                            f"Translating {language} (batch {batch_index + 1}/{len(text_batches)})"
                        )
                
                return language, language_results
                
            except Exception as e:
                logger.error(f"Critical error translating {language}: {e}")
                return language, texts  # Fallback to original
        
        # Execute translations with controlled parallelism
        max_workers = min(len(self.api_keys), len(target_languages), 3)  # Limit concurrent requests
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_lang = {
                executor.submit(translate_language, lang, i): lang 
                for i, lang in enumerate(target_languages)
            }
            
            for future in concurrent.futures.as_completed(future_to_lang):
                language = future_to_lang[future]
                try:
                    lang, translated_texts = future.result(timeout=300)  # 5 minute timeout
                    results[lang] = translated_texts
                    logger.info(f"Collected results for {language}")
                    
                except Exception as e:
                    logger.error(f"Failed to get results for {language}: {e}")
                    results[language] = texts  # Fallback
        
        # Log performance statistics
        translation_time = time.time() - start_time
        self.performance_stats['translation_time'] = translation_time
        
        logger.info(f"Parallel translation completed in {translation_time:.2f}s")
        logger.info(f"Success rate: {self.performance_stats['successful_translations']}"
                   f"/{self.performance_stats['successful_translations'] + self.performance_stats['failed_translations']}")
        logger.info(f"Total retries performed: {self.performance_stats['retries_performed']}")
        
        return results
    
    def _parse_translation_response(self, response_text, expected_count):
        """Enhanced parsing of translation responses"""
        try:
            translations = []
            lines = response_text.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Try multiple patterns
                patterns = [
                    r'^\d+\.\s*(.+)$',  # "1. Translation"
                    r'^\d+\)\s*(.+)$',  # "1) Translation"
                    r'^\d+:\s*(.+)$',   # "1: Translation"
                    r'^-\s*(.+)$',      # "- Translation"
                ]
                
                for pattern in patterns:
                    match = re.match(pattern, line)
                    if match:
                        translations.append(match.group(1).strip())
                        break
                else:
                    # If no pattern matches and we don't have enough translations
                    if len(translations) < expected_count and line:
                        translations.append(line)
            
            # Ensure correct count
            while len(translations) < expected_count:
                translations.append("")
            
            return translations[:expected_count]
            
        except Exception as e:
            logger.error(f"Error parsing translation response: {e}")
            return [""] * expected_count
    
    # ... (rest of the methods remain the same: extract_audio_and_transcribe_optimized, 
    # improve_subtitle_timing_optimized, create_srt_from_segments, etc.)
    
    def get_file_hash(self, file_path):
        """Generate MD5 hash for file caching"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            logger.error(f"Error generating file hash: {e}")
            return str(time.time())
    
    def extract_audio_and_transcribe_optimized(self, video_path, output_dir=None, progress_callback=None):
        """Optimized transcription with caching"""
        logger.info(f"Starting transcription: {os.path.basename(video_path)}")
        
        if output_dir is None:
            output_dir = os.path.dirname(video_path)
        
        # Check cache first
        file_hash = self.get_file_hash(video_path)
        cached_result = self.load_from_cache(file_hash, 'transcription')
        
        if cached_result:
            logger.info("Using cached transcription")
            if progress_callback:
                progress_callback(60, "Loading from cache...")
            return cached_result
        
        # Perform transcription
        start_time = time.time()
        
        if progress_callback:
            progress_callback(15, f"Transcribing with {self.model_size} model...")
        
        try:
            result = self.model.transcribe(
                video_path,
                word_timestamps=True,
                verbose=False,
                language='en',
                temperature=0.0,
                fp16=True,
            )
            
            transcription_time = time.time() - start_time
            self.performance_stats['transcription_time'] = transcription_time
            
            logger.info(f"Transcription completed in {transcription_time:.2f}s")
            logger.info(f"Found {len(result['segments'])} segments")
            
            # Save to cache
            self.save_to_cache(result, file_hash, 'transcription')
            
            if progress_callback:
                progress_callback(60, f"Transcription completed: {len(result['segments'])} segments")
            
            return result
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise
    
    def save_to_cache(self, data, cache_key, cache_type='transcription'):
        """Save data to cache"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}_{cache_type}.pkl")
        
        cache_data = {
            'data': data,
            'timestamp': time.time(),
            'model_size': self.model_size,
            'version': '2.0'
        }
        
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)
            logger.info(f"Saved to cache: {cache_type}")
            return True
        except Exception as e:
            logger.error(f"Cache save error: {e}")
            return False
    
    def load_from_cache(self, cache_key, cache_type='transcription'):
        """Load data from cache"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}_{cache_type}.pkl")
        
        try:
            if not os.path.exists(cache_file):
                return None
            
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            
            if isinstance(cache_data, dict) and 'data' in cache_data:
                # Check if cache is not too old (7 days)
                if time.time() - cache_data.get('timestamp', 0) < 7 * 24 * 3600:
                    logger.info(f"Cache hit: {cache_type}")
                    self.performance_stats['cache_hits'] += 1
                    return cache_data['data']
            
            return None
            
        except Exception as e:
            logger.error(f"Cache load error: {e}")
            return None