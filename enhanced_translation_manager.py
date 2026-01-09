# enhanced_translation_manager.py

import time
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import google.generativeai as genai
import threading
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import re

safety_settings = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

logger = logging.getLogger(__name__)

# Safe import for Google Translate
try:
    from googletrans import Translator
    GOOGLE_TRANSLATE_AVAILABLE = True
except ImportError:
    Translator = None
    GOOGLE_TRANSLATE_AVAILABLE = False
    logger.warning("googletrans not available, falling back to basic translation")

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
        # Prioritize Quota/Billing errors (longer cooldown)
        if any(keyword in error_lower for keyword in ['quota', 'billing']):
            self.status = APIKeyStatus.QUOTA_EXCEEDED
            self.cooldown_until = time.time() + 3600  # 1 hour cooldown
        elif any(keyword in error_lower for keyword in ['rate limit', '429', 'too many requests', 'exceeded']):
            self.status = APIKeyStatus.RATE_LIMITED
            self.cooldown_until = time.time() + 60  # 1 minute cooldown
        elif any(keyword in error_lower for keyword in ['timeout', 'deadline', '504']):
            self.status = APIKeyStatus.ERROR
            self.cooldown_until = time.time() + 30  # 30 second cooldown
        else:
            self.status = APIKeyStatus.ERROR
            self.cooldown_until = time.time() + 10  # 10 second cooldown

# Global registry to share key states across different tasks/instances
_global_key_states: Dict[str, APIKeyInfo] = {}

class EnhancedTranslationManager:
    """
    Enhanced translation manager with intelligent API key switching and fallback
    """
    
    def __init__(self, gemini_api_keys: List[str] = None, socketio=None):
        self.gemini_keys = []
        self.google_translator = None
        self.current_key_index = 0
        self.lock = threading.Lock()
        self.socketio = socketio
        self.current_task_id = None
        
        # Initialize Gemini API keys
        if gemini_api_keys:
            for key in gemini_api_keys:
                clean_key = key.strip()
                if clean_key:
                    # Use global state if exists to persist quota/error status across tasks
                    if clean_key in _global_key_states:
                        self.gemini_keys.append(_global_key_states[clean_key])
                    else:
                        new_info = APIKeyInfo(clean_key, APIKeyStatus.ACTIVE)
                        _global_key_states[clean_key] = new_info
                        self.gemini_keys.append(new_info)
        
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
        
        # Ensure we try at least as many times as we have keys, or 3, whichever is greater
        self.max_retries = max(3, len(self.gemini_keys))
        self.batch_size = 50  # Larger batches to reduce API call overhead
        
        logger.info(f"Translation manager initialized with {len(self.gemini_keys)} Gemini keys")
    def set_task_id(self, task_id: str):
        """Set current task ID for progress updates"""
        self.current_task_id = task_id
    def emit_progress(self, step: str, message: str, progress: float, target_language: str, **kwargs):
        """Emit progress update via WebSocket"""
        if self.socketio and self.current_task_id:
            data = {
                'task_id': self.current_task_id,
                'step': step,
                'message': message,
                'progress': progress,
                'status': 'processing',
                'target_language': target_language,
                **kwargs
            }
            
            try:
                # Emit with the SAME event name as other progress updates
                self.socketio.emit('progress_translation', data, room=self.current_task_id)
                
                # Aggressive flush for eventlet
                import eventlet
                eventlet.sleep(0)
                
                # logger.info(f"📡 Translation progress: {step} - {progress*100:.0f}% - {message}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to emit translation progress: {e}")

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
                                   context: str = "", previous_context_lines: List[str] = None) -> Tuple[List[str], bool]:
        """
        Translate a batch of texts using Gemini with smart API key switching
        """
        if not self.gemini_keys:
            return texts, False

        from shared_state import cancel_flags
        
        if self.current_task_id and cancel_flags.get(self.current_task_id):
            logger.info(f"Gemini translation cancelled before starting")
            return texts, False
        
        # Language mapping
        lang_mapping = {
            'vietnamese': {'code': 'vi', 'name': 'tiếng Việt', 'native': 'Tiếng Việt', 'country': 'Vietnam'},
            'chinese': {'code': 'zh', 'name': 'tiếng Trung', 'native': '中文 (简体)', 'country': 'China'},
            # 'chinese_traditional': {'code': 'zh-tw', 'name': 'tiếng Trung (phồn thể)', 'native': '中文 (繁體)', 'country': 'Taiwan'},
            'korean': {'code': 'ko', 'name': 'tiếng Hàn', 'native': '한국어', 'country': 'South Korea'},
            'japanese': {'code': 'ja', 'name': 'tiếng Nhật', 'native': '日本語', 'country': 'Japan'},
            'french': {'code': 'fr', 'name': 'tiếng Pháp', 'native': 'Français', 'country': 'France'},
            'spanish': {'code': 'es', 'name': 'tiếng Tây Ban Nha', 'native': 'Español', 'country': 'Spain'},
            'german': {'code': 'de', 'name': 'tiếng Đức', 'native': 'Deutsch', 'country': 'Germany'},
            'italian': {'code': 'it', 'name': 'tiếng Ý', 'native': 'Italiano', 'country': 'Italy'},
            'portuguese': {'code': 'pt', 'name': 'tiếng Bồ Đào Nha', 'native': 'Português', 'country': 'Portugal'},
            'russian': {'code': 'ru', 'name': 'tiếng Nga', 'native': 'Русский', 'country': 'Russia'},
            'arabic': {'code': 'ar', 'name': 'tiếng Ả Rập', 'native': 'العربية', 'country': 'Egypt'},
            'thai': {'code': 'th', 'name': 'tiếng Thái', 'native': 'ไทย', 'country': 'Thailand'},
            'hindi': {'code': 'hi', 'name': 'tiếng Hindi', 'native': 'हिन्दी', 'country': 'India'},
            'indonesian': {'code': 'id', 'name': 'tiếng Indonesia', 'native': 'Bahasa Indonesia', 'country': 'Indonesia'},
            'malaysian': {'code': 'ms', 'name': 'tiếng Malaysia', 'native': 'Bahasa Malaysia', 'country': 'Malaysia'},
            'dutch': {'code': 'nl', 'name': 'tiếng Hà Lan', 'native': 'Nederlands', 'country': 'Netherlands'},
            'swedish': {'code': 'sv', 'name': 'tiếng Thụy Điển', 'native': 'Svenska', 'country': 'Sweden'},
            'norwegian': {'code': 'no', 'name': 'tiếng Na Uy', 'native': 'Norsk', 'country': 'Norway'},
            'danish': {'code': 'da', 'name': 'tiếng Đan Mạch', 'native': 'Dansk', 'country': 'Denmark'},
            'polish': {'code': 'pl', 'name': 'tiếng Ba Lan', 'native': 'Polski', 'country': 'Poland'},
            'czech': {'code': 'cs', 'name': 'tiếng Séc', 'native': 'Čeština', 'country': 'Czech Republic'},
            'hungarian': {'code': 'hu', 'name': 'tiếng Hungary', 'native': 'Magyar', 'country': 'Hungary'},
            'turkish': {'code': 'tr', 'name': 'tiếng Thổ Nhĩ Kỳ', 'native': 'Türkçe', 'country': 'Turkey'},
            'greek': {'code': 'el', 'name': 'tiếng Hy Lạp', 'native': 'Ελληνικά', 'country': 'Greece'},
            'hebrew': {'code': 'he', 'name': 'tiếng Hebrew', 'native': 'עברית', 'country': 'Israel'},
            'finnish': {'code': 'fi', 'name': 'tiếng Phần Lan', 'native': 'Suomi', 'country': 'Finland'},
            'ukrainian': {'code': 'uk', 'name': 'tiếng Ukraine', 'native': 'Українська', 'country': 'Ukraine'},
            'bulgarian': {'code': 'bg', 'name': 'tiếng Bulgaria', 'native': 'Български', 'country': 'Bulgaria'},
            'romanian': {'code': 'ro', 'name': 'tiếng Romania', 'native': 'Română', 'country': 'Romania'},
            'croatian': {'code': 'hr', 'name': 'tiếng Croatia', 'native': 'Hrvatski', 'country': 'Croatia'},
            'serbian': {'code': 'sr', 'name': 'tiếng Serbia', 'native': 'Српски', 'country': 'Serbia'},
            'slovenian': {'code': 'sl', 'name': 'tiếng Slovenia', 'native': 'Slovenščina', 'country': 'Slovenia'},
            'slovak': {'code': 'sk', 'name': 'tiếng Slovakia', 'native': 'Slovenčina', 'country': 'Slovakia'},
            'lithuanian': {'code': 'lt', 'name': 'tiếng Lithuania', 'native': 'Lietuvių', 'country': 'Lithuania'},
            'latvian': {'code': 'lv', 'name': 'tiếng Latvia', 'native': 'Latviešu', 'country': 'Latvia'},
            'estonian': {'code': 'et', 'name': 'tiếng Estonia', 'native': 'Eesti', 'country': 'Estonia'},
            'english': {'code': 'en', 'name': 'English', 'native': 'English', 'country': 'United States'}
        }
        
        lang_info = lang_mapping.get(target_language.lower())
        if not lang_info:
            logger.warning(f"Unsupported language: {target_language}")
            return texts, False

        prev_context_str = ""
        if previous_context_lines and len(previous_context_lines) > 0:
            prev_context_str = "\n".join(previous_context_lines)
        
        # Try each available API key
        for attempt in range(self.max_retries):
            if self.current_task_id and cancel_flags.get(self.current_task_id):
                logger.info(f"Gemini translation cancelled at retry {attempt}")
                return texts, False
            key_info = self.get_available_gemini_key()
            
            if not key_info:
                logger.warning("No available Gemini API keys")
                break
            
            try:
                # Configure API key
                genai.configure(api_key=key_info.key)
                model = genai.GenerativeModel(
                    'gemini-2.0-flash-lite',
                    system_instruction=f"""
                    You are a professional subtitle translator for {lang_info['country']}.
                    CRITICAL RULES:
                    1. ONE LINE IN = ONE LINE OUT. 
                    2. If the input has {len(texts)} lines, the output MUST have exactly {len(texts)} lines.
                    3. NEVER merge two short lines into one.
                    4. NEVER skip lines, even if they are just sounds like "Ah", "Hmm".
                    5. Maintain line breaks exactly.
                    RELATIONSHIPS & PRONOUNS:
                    - Consistency is key. Infer relationships (Father/Daughter, Boss/Employee) and use appropriate pronouns (Cha/Con, Sếp/Em).
                    - Do not switch pronouns randomly.
                    """,
                )
                
                # Create optimized prompt
                joined_texts = "\n".join(texts)
                prompt = f"""
### CONTEXT (STORY SO FAR) - DO NOT TRANSLATE THIS PART:
{prev_context_str if prev_context_str else "No previous context (Start of file)."}
### USER ADDITIONAL CONTEXT:
{context}
### TARGET LANGUAGE:
{target_language}
### INPUT TEXT TO TRANSLATE (EXACTLY {len(texts)} LINES):
{joined_texts}
### OUTPUT FORMAT:
Return exactly {len(texts)} translated lines. 
Preserve line breaks. 
Do not include line numbers in the output.
"""

                # logger.info(f"Translating batch of {len(texts)} texts to {target_language} using {key_info.short_key}")
                # logger.info(f"Prompt length: {len(prompt)} characters, {prompt}")
                
                if self.current_task_id and cancel_flags.get(self.current_task_id):
                    logger.info("Cancelled before Gemini API call")
                    return texts, False
                # Make API request with timeout
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.3,
                        top_p=1,
                        top_k=1,
                    ),
                    safety_settings=safety_settings,
                )
                
                if self.current_task_id and cancel_flags.get(self.current_task_id):
                    logger.info("Cancelled after Gemini API call")
                    return texts, False
                # FIX: Truy cập response text một cách an toàn
                response_text = self._extract_response_text(response)
            
                if not response_text or len(response_text.strip()) < 10:
                    logger.warning(f"Empty or too short response from {key_info.short_key}: '{response_text[:100]}'")
                    if attempt < self.max_retries - 1:
                        time.sleep(2)  # Wait before retry
                        continue
                    return texts, False
                
                # Parse response
                translations = self._parse_gemini_response(response_text, len(texts))
                
                # Validate quality
                valid_translations = [t for t in translations if t.strip()]
                if len(valid_translations) >= len(texts) * 0.7:  # At least 70% valid
                    key_info.mark_success()
                    # logger.info(f"Successfully translated {len(valid_translations)}/{len(texts)} using {key_info.short_key}")
                    
                    # Fill empty translations with originals
                    final_translations = []
                    for i, (original, translated) in enumerate(zip(texts, translations)):
                        if translated.strip():
                            final_translations.append(translated)
                        else:
                            final_translations.append(original)
                            logger.warning(f"Using original for segment {i+1}: '{original[:50]}'")
                    
                    return final_translations, True
                else:
                    logger.warning(f"Poor translation quality: {len(valid_translations)}/{len(texts)} valid")


            except Exception as e:
                error_msg = str(e)
                key_info.mark_error(error_msg)
                logger.warning(f"Translation error with {key_info.short_key}: {error_msg}")
                
                # Check for specific error types
                if any(keyword in error_msg.lower() for keyword in 
                    ['quota', 'billing', 'exceeded', 'resource_exhausted']):
                    logger.error(f"Quota/billing error for {key_info.short_key}. Switching to next key...")
                    continue
                
                if attempt < self.max_retries - 1:
                    wait_time = min(2 ** attempt, 10)  # Exponential backoff, max 10s
                    logger.info(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
        logger.warning("All Gemini attempts failed, will fallback to Google Translate")
        return texts, False  # Failed with all API keys

    def translate_batch_with_google(self, texts: List[str], target_language: str) -> List[str]:
        """
        Fallback translation using Google Translate
        """
        if not self.google_translator:
            logger.warning("Google Translate not available")
            return texts

        from shared_state import cancel_flags
        
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
        
        # logger.info(f"Using Google Translate fallback for {len(texts)} texts to {target_language}")
        
        translations = []
        for i, text in enumerate(texts):
            try:
                if self.current_task_id and cancel_flags.get(self.current_task_id):
                    logger.info(f"Google Translate cancelled at text {i}/{len(texts)}")
                    # Return what we have + originals for rest
                    remaining = texts[len(translations):]
                    translations.extend(remaining)
                    break
                if not text.strip():
                    translations.append("")
                    continue
                
                result = self.google_translator.translate(text, src='en', dest=target_code)
                translations.append(result.text if result.text else text)
                
                # Small delay to avoid rate limiting
                time.sleep(0.1)
                
                if i % 10 == 0 or i == len(texts) - 1:
                    progress = (i + 1) / len(texts)
                    self.emit_progress(
                        "translation",
                        f"Google Translate: {i+1}/{len(texts)} texts",
                        progress,
                        target_language
                    )
                
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
        from shared_state import cancel_flags  # Import here to avoid circular import at module level
        # Process in batches
        all_translations = []
        total_batches = (len(texts) + self.batch_size - 1) // self.batch_size
        
        last_translated_batch = []
        for batch_idx in range(total_batches):
            # Cancel check before each batch
            if self.current_task_id and cancel_flags.get(self.current_task_id):
                logger.info(f"Translation cancelled for task {self.current_task_id}")
                remaining = texts[len(all_translations):]
                all_translations.extend(remaining)
                break
            start_idx = batch_idx * self.batch_size
            end_idx = min(start_idx + self.batch_size, len(texts))
            batch_texts = texts[start_idx:end_idx]

            batch_progress = (batch_idx + 1) / total_batches

            logger.info(f"Processing batch {batch_idx + 1}/{total_batches} ({len(batch_texts)} texts)")

            # Emit progress BEFORE processing
            self.emit_progress(
                "translation",
                f"Translating to {target_language}: {batch_progress*100:.0f}% (batch {batch_idx + 1}/{total_batches})",
                batch_progress,
                target_language,
            )
            
            if self.current_task_id and cancel_flags.get(self.current_task_id):
                logger.info(f"Translation cancelled before processing batch {batch_idx+1}")
                remaining = texts[len(all_translations):]
                all_translations.extend(remaining)
                return all_translations

            # Try Gemini first
            context_window = last_translated_batch[-5:] if last_translated_batch else []
            
            translations, success = self.translate_batch_with_gemini(
                batch_texts, target_language, context, previous_context_lines=context_window
            )
            
            if self.current_task_id and cancel_flags.get(self.current_task_id):
                logger.info(f"Translation cancelled after Gemini batch {batch_idx+1}")
                all_translations.extend(translations)
                remaining = texts[len(all_translations):]
                all_translations.extend(remaining)
                return all_translations

            if not success:
                logger.warning(f"Gemini translation failed for batch {batch_idx + 1}, trying Google Translate")
                if self.current_task_id and cancel_flags.get(self.current_task_id):
                    logger.info(f"Translation cancelled before Google Translate fallback")
                    all_translations.extend(batch_texts)  # Use originals
                    remaining = texts[len(all_translations):]
                    all_translations.extend(remaining)
                    return all_translations
                # Emit fallback notification
                self.emit_progress(
                    "translation",
                    f"Using Google Translate fallback for {target_language}: {batch_progress*100:.0f}% (batch {batch_idx + 1}/{total_batches})",
                    batch_progress,
                    target_language,
                )

                translations = self.translate_batch_with_google(batch_texts, target_language)

            all_translations.extend(translations)
            
            last_translated_batch = translations
            
            if self.current_task_id and cancel_flags.get(self.current_task_id):
                logger.info(f"Translation cancelled after batch {batch_idx+1} completed")
                remaining = texts[len(all_translations):]
                all_translations.extend(remaining)
                return all_translations

            # Small delay between batches
            if batch_idx < total_batches - 1:
                import eventlet
                eventlet.sleep(2.0)
            if self.current_task_id and cancel_flags.get(self.current_task_id):
                logger.info(f"Translation cancelled after batch {batch_idx+1}")
                remaining = texts[len(all_translations):]
                all_translations.extend(remaining)
                break
        # Final completion emit
        self.emit_progress(
            "translation",
            f"Completed translation to {target_language}",
            1.0,
            target_language,
        )
        logger.info(f"Translation completed: {len(all_translations)} results")
        return all_translations
    
    def _parse_gemini_response(self, response_text: str, expected_count: int) -> List[str]:
        """Parse Gemini response and extract translations"""
        try:
            if not response_text:
                return [""] * expected_count
                
            translations = []
            
            # 1. Split the text into lines, removing excess whitespace
            lines = response_text.strip().split('\n')

            
            # 2. Use a more flexible Regex to capture the index (e.g. "1.", "1:", "1-", or "Segment 1:")
            # This pattern finds: (Number) (Optional separator) (Translated content)
            cleaned_lines = []
            for line in lines:
                line = line.strip()
                # Remove leading numbering if present (just in case model hallucinates it)
                line = re.sub(r'^\d+[.:\-\)]\s*', '', line)
                cleaned_lines.append(line)


            if len(cleaned_lines) > expected_count:
                # Try filtering empty lines if we have too many
                non_empty = [l for l in cleaned_lines if l]
                if len(non_empty) == expected_count:
                    cleaned_lines = non_empty
                else:
                    # Case where the model breaks down a segment into multiple lines, so we concatenate them together with a single space separator.
                    cleaned_lines = cleaned_lines[:expected_count]

            
            while len(cleaned_lines) < expected_count:
                cleaned_lines.append("")
            return cleaned_lines
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

    def _extract_response_text(self, response) -> str:
        """
        Safely extract text by ONLY accessing the candidates/parts structure, 
        completely ignoring the problematic response.text accessor.
        """
        if hasattr(response, 'usage_metadata'):
            usage = response.usage_metadata
            logger.info(f"📊 Token Details:")
            logger.info(f"   Input: {usage.prompt_token_count} | Output: {usage.candidates_token_count} | Total: {usage.total_token_count}")
        
        # Kiểm tra và log finish_reason trước
        finish_reason = getattr(getattr(response, "candidates", [None])[0], "finish_reason", None)
        if finish_reason:
            logger.debug(f"Response finish reason: {finish_reason}")
            
        if finish_reason and finish_reason.value in [2, 3]: # MAX_TOKENS (2) or SAFETY (3)
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
        
        logger.error(f"Could not extract text from Gemini response (Failed candidates/parts check). Raw: {response}")
        return ""

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