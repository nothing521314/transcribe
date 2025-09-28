# enhanced_translation_manager.py

import time
import random
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import google.generativeai as genai
import threading
import queue

# Safe import for Google Translate
try:
    from googletrans import Translator
    GOOGLE_TRANSLATE_AVAILABLE = True
except ImportError:
    Translator = None
    GOOGLE_TRANSLATE_AVAILABLE = False
    logger.warning("googletrans not available, falling back to basic translation")

logger = logging.getLogger(__name__)

class APIKeyStatus(Enum):
    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    ERROR = "error"
    COOLING_DOWN = "cooling_down"

@dataclass
class APIKeyInfo:
    key: str
    status: APIKeyStatus
    usage_count: int = 0
    error_count: int = 0
    last_used: float = 0
    last_error: Optional[str] = None
    cooldown_until: float = 0
    consecutive_errors: int = 0
    
    @property
    def short_key(self) -> str:
        return f"...{self.key[-8:]}" if len(self.key) > 8 else self.key
    
    def is_available(self) -> bool:
        """Check if API key is available for use"""
        current_time = time.time()
        
        # Check if still in cooldown
        if self.cooldown_until > current_time:
            return False
            
        # Don't use keys with too many consecutive errors
        if self.consecutive_errors >= 5:
            return False
            
        # Available if active or if enough time passed since last error
        return (self.status == APIKeyStatus.ACTIVE or 
                (current_time - self.last_used > 60))  # 1 minute recovery
    
    def mark_success(self):
        """Mark successful API call"""
        self.status = APIKeyStatus.ACTIVE
        self.usage_count += 1
        self.last_used = time.time()
        self.consecutive_errors = 0
        self.cooldown_until = 0
    
    def mark_error(self, error_msg: str):
        """Mark API error and determine appropriate status"""
        self.error_count += 1
        self.consecutive_errors += 1
        self.last_error = error_msg
        self.last_used = time.time()
        
        error_lower = error_msg.lower()
        
        # Classify error types
        if any(keyword in error_lower for keyword in ['rate limit', '429', 'too many requests']):
            self.status = APIKeyStatus.RATE_LIMITED
            self.cooldown_until = time.time() + 60  # 1 minute cooldown
        elif any(keyword in error_lower for keyword in ['quota', 'exceeded', 'billing']):
            self.status = APIKeyStatus.QUOTA_EXCEEDED
            self.cooldown_until = time.time() + 3600  # 1 hour cooldown
        elif any(keyword in error_lower for keyword in ['timeout', 'deadline', '504']):
            self.status = APIKeyStatus.ERROR
            self.cooldown_until = time.time() + 30  # 30 second cooldown
        else:
            self.status = APIKeyStatus.ERROR
            self.cooldown_until = time.time() + 10  # 10 second cooldown

class EnhancedTranslationManager:
    """
    Enhanced translation manager with intelligent API key switching and fallback
    """
    
    def __init__(self, gemini_api_keys: List[str] = None):
        self.gemini_keys = []
        self.google_translator = None
        self.current_key_index = 0
        self.lock = threading.Lock()
        
        # Initialize Gemini API keys
        if gemini_api_keys:
            for key in gemini_api_keys:
                if key and key.strip():
                    self.gemini_keys.append(APIKeyInfo(key.strip(), APIKeyStatus.ACTIVE))
        
        # Initialize Google Translate fallback
        if GOOGLE_TRANSLATE_AVAILABLE:
            try:
                self.google_translator = Translator()
                logger.info("Google Translate fallback initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Google Translate: {e}")
                self.google_translator = None
        else:
            self.google_translator = None
            logger.warning("Google Translate not available (googletrans not installed)")
        
        self.max_retries = 3
        self.batch_size = 15  # Smaller batches for better reliability
        
        logger.info(f"Translation manager initialized with {len(self.gemini_keys)} Gemini keys")
    
    def get_available_gemini_key(self) -> Optional[APIKeyInfo]:
        """Get next available Gemini API key"""
        with self.lock:
            # First pass: try to find an active key
            for _ in range(len(self.gemini_keys)):
                key_info = self.gemini_keys[self.current_key_index]
                self.current_key_index = (self.current_key_index + 1) % len(self.gemini_keys)
                
                if key_info.is_available():
                    return key_info
            
            # Second pass: try keys that might have recovered
            current_time = time.time()
            for key_info in self.gemini_keys:
                if (key_info.status in [APIKeyStatus.RATE_LIMITED, APIKeyStatus.ERROR] and
                    current_time - key_info.last_used > 120):  # 2 minutes recovery
                    key_info.status = APIKeyStatus.ACTIVE
                    key_info.consecutive_errors = 0
                    return key_info
            
            return None
    
    def translate_batch_with_gemini(self, texts: List[str], target_language: str, 
                                   context: str = "") -> Tuple[List[str], bool]:
        """
        Translate a batch of texts using Gemini with smart API key switching
        """
        if not self.gemini_keys:
            return texts, False
        
        # Language mapping
        lang_mapping = {
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
        
        lang_info = lang_mapping.get(target_language.lower())
        if not lang_info:
            logger.warning(f"Unsupported language: {target_language}")
            return texts, False
        
        # Try each available API key
        for attempt in range(self.max_retries):
            key_info = self.get_available_gemini_key()
            
            if not key_info:
                logger.warning("No available Gemini API keys")
                break
            
            try:
                # Configure API key
                genai.configure(api_key=key_info.key)
                model = genai.GenerativeModel('gemini-1.5-pro')
                
                # Create optimized prompt
                context_part = f"\n\nContext: {context}" if context else ""
                prompt = f"""You are a professional subtitle translator. Translate these English subtitle segments to {lang_info['name']} ({lang_info['native']}).

CRITICAL REQUIREMENTS:
1. Translate meaning and context, NOT word-by-word
2. Keep similar length to maintain subtitle timing
3. Use natural, conversational language
4. Maintain emotional tone and style
5. Handle technical terms appropriately{context_part}

SEGMENTS TO TRANSLATE ({len(texts)} items):
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(texts)])}

Return ONLY the translations in the same order, numbered 1-{len(texts)}.
Do not include explanations or additional text."""

                logger.info(f"Translating batch of {len(texts)} texts to {target_language} using {key_info.short_key}")
                
                # Make API request with timeout
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=2000,
                    )
                )
                
                # Parse response
                translations = self._parse_gemini_response(response.text, len(texts))
                
                # Validate quality
                if len(translations) == len(texts) and self._validate_translations(texts, translations):
                    key_info.mark_success()
                    logger.info(f"Successfully translated batch using {key_info.short_key}")
                    return translations, True
                else:
                    logger.warning(f"Poor translation quality from {key_info.short_key}")
                    if attempt < self.max_retries - 1:
                        continue
                    
            except Exception as e:
                error_msg = str(e)
                key_info.mark_error(error_msg)
                logger.warning(f"Translation error with {key_info.short_key}: {error_msg}")
                
                # Don't retry if it's a quota/billing issue
                if any(keyword in error_msg.lower() for keyword in ['quota', 'billing', 'exceeded']):
                    logger.error(f"Quota exceeded for {key_info.short_key}, marking as unavailable")
                    break
                
                if attempt < self.max_retries - 1:
                    time.sleep(1 * (attempt + 1))  # Exponential backoff
                    continue
        
        return texts, False  # Failed with all API keys
    
    def translate_batch_with_google(self, texts: List[str], target_language: str) -> List[str]:
        """
        Fallback translation using Google Translate
        """
        if not self.google_translator:
            logger.warning("Google Translate not available")
            return texts
        
        # Language code mapping
        lang_codes = {
            'vietnamese': 'vi', 'chinese': 'zh-cn', 'chinese_traditional': 'zh-tw',
            'korean': 'ko', 'japanese': 'ja', 'french': 'fr', 'spanish': 'es',
            'german': 'de', 'italian': 'it', 'portuguese': 'pt', 'russian': 'ru',
            'arabic': 'ar', 'thai': 'th', 'hindi': 'hi', 'indonesian': 'id',
            'malaysian': 'ms', 'dutch': 'nl', 'swedish': 'sv', 'norwegian': 'no',
            'danish': 'da', 'polish': 'pl', 'czech': 'cs', 'hungarian': 'hu',
            'turkish': 'tr', 'greek': 'el', 'hebrew': 'he', 'finnish': 'fi',
            'ukrainian': 'uk', 'bulgarian': 'bg', 'romanian': 'ro',
            'croatian': 'hr', 'serbian': 'sr', 'slovenian': 'sl',
            'slovak': 'sk', 'lithuanian': 'lt', 'latvian': 'lv', 'estonian': 'et'
        }
        
        target_code = lang_codes.get(target_language.lower(), 'vi')
        
        logger.info(f"Using Google Translate fallback for {len(texts)} texts to {target_language}")
        
        translations = []
        for text in texts:
            try:
                if not text.strip():
                    translations.append("")
                    continue
                
                result = self.google_translator.translate(text, src='en', dest=target_code)
                translations.append(result.text if result.text else text)
                
                # Small delay to avoid rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"Google Translate error for text '{text[:50]}...': {e}")
                translations.append(text)  # Fallback to original
        
        logger.info(f"Google Translate completed {len(translations)} translations")
        return translations
    
    def translate_texts(self, texts: List[str], target_language: str, 
                       context: str = "") -> List[str]:
        """
        Main translation method with intelligent fallback
        """
        if not texts:
            return []
        
        logger.info(f"Starting translation of {len(texts)} texts to {target_language}")
        
        # Process in batches
        all_translations = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size
        
        for batch_idx in range(total_batches):
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(texts))
            batch_texts = texts[start_idx:end_idx]
            
            logger.info(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch_texts)} texts)")
            
            # Try Gemini first
            translations, success = self.translate_batch_with_gemini(
                batch_texts, target_language, context
            )
            
            if not success:
                logger.warning(f"Gemini translation failed for batch {batch_idx + 1}, trying Google Translate")
                translations = self.translate_batch_with_google(batch_texts, target_language)
            
            all_translations.extend(translations)
            
            # Small delay between batches
            if batch_idx < total_batches - 1:
                time.sleep(0.5)
        
        logger.info(f"Translation completed: {len(all_translations)} results")
        return all_translations
    
    def _parse_gemini_response(self, response_text: str, expected_count: int) -> List[str]:
        """Parse Gemini response and extract translations"""
        try:
            translations = []
            lines = response_text.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Match numbered lines (1. text, 2. text, etc.)
                import re
                match = re.match(r'^\d+\.\s*(.+)$', line)
                if match:
                    translations.append(match.group(1))
            
            # Ensure correct count
            while len(translations) < expected_count:
                translations.append("")
            
            return translations[:expected_count]
            
        except Exception as e:
            logger.error(f"Error parsing Gemini response: {e}")
            return [""] * expected_count
    
    def _validate_translations(self, original_texts: List[str], translations: List[str]) -> bool:
        """Validate translation quality"""
        if len(original_texts) != len(translations):
            return False
        
        # Check that at least 80% of translations are non-empty
        non_empty_translations = sum(1 for t in translations if t.strip())
        return non_empty_translations >= len(translations) * 0.8
    
    def get_api_status(self) -> Dict:
        """Get current API key status"""
        status = {
            'gemini_keys': [],
            'google_translate': self.google_translator is not None,
            'total_usage': sum(key.usage_count for key in self.gemini_keys),
            'total_errors': sum(key.error_count for key in self.gemini_keys)
        }
        
        for key_info in self.gemini_keys:
            status['gemini_keys'].append({
                'key': key_info.short_key,
                'status': key_info.status.value,
                'usage_count': key_info.usage_count,
                'error_count': key_info.error_count,
                'consecutive_errors': key_info.consecutive_errors,
                'available': key_info.is_available(),
                'last_error': key_info.last_error
            })
        
        return status
    
    def reset_key_errors(self, key_short: str = None):
        """Reset error counts for API keys"""
        reset_count = 0
        for key_info in self.gemini_keys:
            if key_short is None or key_info.short_key == key_short:
                key_info.consecutive_errors = 0
                key_info.status = APIKeyStatus.ACTIVE
                key_info.cooldown_until = 0
                reset_count += 1
        
        logger.info(f"Reset {reset_count} API key error states")
        return reset_count