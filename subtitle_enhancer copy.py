import re
import time
import logging
from typing import List, Dict
import google.generativeai as genai

logger = logging.getLogger(__name__)


class SubtitleEnhancer:
    """Enhanced subtitle processor for merging, optimizing, and rewriting subtitles"""

    def __init__(self, api_key: str):
        """Initialize with Gemini API key"""
        self.api_key = api_key
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-2.5-flash")
        logger.info("SubtitleEnhancer initialized")

    def parse_srt(self, srt_content: str) -> List[Dict]:
        """Parse SRT content into segments"""
        segments = []
        
        # Normalize line endings and remove BOM if present
        srt_content = srt_content.replace('\r\n', '\n').replace('\r', '\n')
        if srt_content.startswith('\ufeff'):
            srt_content = srt_content[1:]
        
        # Split by empty lines (one or more consecutive newlines)
        # Use regex to handle multiple newlines and whitespace
        blocks = re.split(r'\n\s*\n', srt_content.strip())
        
        logger.info(f"Found {len(blocks)} blocks in SRT content")

        for idx, block in enumerate(blocks):
            # Skip empty blocks
            if not block.strip():
                continue
                
            lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
            
            # Debug first few blocks
            if idx < 3:
                logger.info(f"Block {idx}: {len(lines)} lines - {lines}")
            
            # SRT format: line 0 = number, line 1 = timing, line 2+ = text
            if len(lines) >= 3:
                try:
                    # Skip the index number (first line)
                    # Second line should be timing
                    time_line = lines[1]
                    
                    # Handle different arrow formats
                    if " --> " in time_line:
                        times = time_line.split(" --> ")
                    elif "-->" in time_line:
                        times = time_line.split("-->")
                    else:
                        logger.warning(f"Invalid timing format in block {idx}: {time_line}")
                        continue
                    
                    if len(times) != 2:
                        logger.warning(f"Invalid timing split in block {idx}: {time_line}")
                        continue
                    
                    start = self._parse_srt_time(times[0])
                    end = self._parse_srt_time(times[1])
                    
                    # Validate times
                    if start < 0 or end < 0 or end <= start:
                        logger.warning(f"Invalid times in block {idx}: start={start}, end={end}")
                        continue

                    # Get text (lines 2 onwards, join with space)
                    text = " ".join(lines[2:])
                    
                    if not text.strip():
                        logger.warning(f"Empty text in block {idx}")
                        continue

                    segments.append({"start": start, "end": end, "text": text})
                    
                except Exception as e:
                    logger.warning(f"Failed to parse SRT block {idx}: {e} - Block: {block[:100]}")
                    continue
            elif len(lines) == 2:
                # Sometimes SRT has only 2 lines (no text)
                logger.warning(f"Skipping block {idx}: only timing, no text")
            else:
                if idx < 10:  # Only log first 10 skipped blocks
                    logger.warning(f"Skipping block {idx}: only {len(lines)} lines - {lines}")

        logger.info(f"Successfully parsed {len(segments)} subtitle segments from {len(blocks)} blocks")
        
        if len(segments) == 0:
            logger.error("No segments parsed! Check SRT format.")
            logger.error(f"First 500 chars of content: {srt_content[:500]}")
        
        return segments

    def _parse_srt_time(self, time_str: str) -> float:
        """Parse SRT time format to seconds"""
        try:
            time_str = time_str.strip().replace(",", ".")
            parts = time_str.split(":")
            
            if len(parts) != 3:
                logger.error(f"Invalid time format: {time_str} (expected HH:MM:SS.mmm)")
                return 0.0
            
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
            
        except Exception as e:
            logger.error(f"Failed to parse time '{time_str}': {e}")
            return 0.0

    def _format_srt_time(self, seconds: float) -> str:
        """Format seconds to SRT time format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def merge_lines(self, segments: List[Dict]) -> List[Dict]:
        """Merge consecutive subtitle lines (even with odd)"""
        merged = []

        for i in range(0, len(segments), 2):
            if i + 1 < len(segments):
                # Merge two consecutive segments
                seg1 = segments[i]
                seg2 = segments[i + 1]

                merged.append(
                    {
                        "start": seg1["start"],
                        "end": seg2["end"],
                        "text": f"{seg1['text']} {seg2['text']}",
                    }
                )
            else:
                # Last segment (odd number)
                merged.append(segments[i])

        logger.info(f"Merged {len(segments)} segments into {len(merged)}")
        return merged

    def optimize_text_batch(self, texts: List[str]) -> List[str]:
        """Optimize text batch with Gemini"""
        try:
            prompt = f"""Optimize these English subtitle texts by:
1. Fixing spelling errors
2. Removing special characters (keep only letters, numbers, basic punctuation: . , ! ? ' -)
3. Adding proper punctuation (periods, commas) where needed
4. Making the text natural and readable

CRITICAL: Return ONLY the optimized texts, numbered 1-{len(texts)}
Each optimized text must be on ONE SINGLE LINE after its number.
Format: "1. [optimized text]" then newline, "2. [optimized text]" then newline, etc.
Do NOT add explanations or extra text.

Original texts:
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(texts)])}

Return optimized texts (one per line):"""

            response_text = self._call_gemini_with_retry(prompt, temperature=0.3)

            # Parse response - collect all lines for each numbered item
            optimized = []
            current_text = ""
            current_num = 0
            
            for line in response_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                    
                # Check if line starts with a number
                match = re.match(r"^(\d+)\.\s*(.+)$", line)
                if match:
                    # If we have accumulated text, save it
                    if current_text and current_num > 0:
                        optimized.append(current_text.strip())
                    
                    # Start new item
                    current_num = int(match.group(1))
                    current_text = match.group(2)
                else:
                    # Continue current item (multi-line response)
                    if current_num > 0:
                        current_text += " " + line
            
            # Don't forget the last item
            if current_text and current_num > 0:
                optimized.append(current_text.strip())

            # Ensure we have the right count
            while len(optimized) < len(texts):
                optimized.append(texts[len(optimized)])

            logger.info(f"Optimized {len(optimized)} texts from batch of {len(texts)}")
            return optimized[: len(texts)]

        except Exception as e:
            logger.error(f"Text optimization error: {e}")
            return texts

    def rewrite_text_batch(self, texts: List[str]) -> List[str]:
        """Rewrite a batch of texts with different structure but same meaning"""
        try:
            prompt = f"""Rewrite these English subtitle texts with different sentence structures, but keep the exact same meaning.

Requirements:
- Change the sentence structure and word order for EACH text
- Use synonyms where appropriate
- Keep the meaning identical
- Make it natural and fluent
- Return ONLY the rewritten texts, numbered 1-{len(texts)}
- Each rewritten text must be on ONE SINGLE LINE after its number
- Format: "1. [rewritten text]" then newline, "2. [rewritten text]" then newline, etc.
- Do NOT add explanations or extra text

Original texts:
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(texts)])}

Return rewritten texts (one per line):"""

            response_text = self._call_gemini_with_retry(prompt, temperature=0.7)
            
            # Parse response - collect all lines for each numbered item
            rewritten = []
            current_text = ""
            current_num = 0
            
            for line in response_text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                    
                # Check if line starts with a number
                match = re.match(r"^(\d+)\.\s*(.+)$", line)
                if match:
                    # If we have accumulated text, save it
                    if current_text and current_num > 0:
                        rewritten.append(current_text.strip())
                    
                    # Start new item
                    current_num = int(match.group(1))
                    current_text = match.group(2)
                else:
                    # Continue current item (multi-line response)
                    if current_num > 0:
                        current_text += " " + line
            
            # Don't forget the last item
            if current_text and current_num > 0:
                rewritten.append(current_text.strip())

            # Ensure we have the right count
            while len(rewritten) < len(texts):
                rewritten.append(texts[len(rewritten)])

            logger.info(f"Rewritten {len(rewritten)} texts from batch of {len(texts)}")
            return rewritten[: len(texts)]

        except Exception as e:
            logger.error(f"Text rewrite error: {e}")
            return texts

    def _call_gemini_with_retry(self, prompt: str, temperature: float = 0.3, max_retries: int = 3) -> str:
        """Call Gemini API with retry logic for rate limits"""
        for attempt in range(max_retries):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=3000,
                    ),
                )
                return self._extract_response_text(response)
                
            except Exception as e:
                error_msg = str(e)
                
                # Check if it's a rate limit error
                if "429" in error_msg or "quota" in error_msg.lower():
                    # Extract retry delay from error message
                    retry_match = re.search(r'retry in (\d+(?:\.\d+)?)', error_msg)
                    if retry_match:
                        wait_time = float(retry_match.group(1)) + 2  # Add 2s buffer
                    else:
                        wait_time = 60  # Default 60s wait
                    
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limit exceeded after {max_retries} retries")
                        raise
                else:
                    # Other errors, don't retry
                    logger.error(f"Gemini API error: {e}")
                    raise
        
        return ""

    def _extract_response_text(self, response) -> str:
        """Safely extract text from Gemini response"""
        try:
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                content = getattr(candidate, "content", None)

                if content and hasattr(content, "parts"):
                    text_parts = []
                    for part in content.parts:
                        text = getattr(part, "text", "")
                        if text:
                            text_parts.append(text)

                    if text_parts:
                        return "\n".join(text_parts)

            logger.error("Could not extract text from Gemini response")
            return ""

        except Exception as e:
            logger.error(f"Error extracting response text: {e}")
            return ""

    def create_srt_content(self, segments: List[Dict]) -> str:
        """Create SRT content from segments"""
        srt_content = []

        for i, seg in enumerate(segments, 1):
            start_time = self._format_srt_time(seg["start"])
            end_time = self._format_srt_time(seg["end"])
            text = seg["text"]

            srt_entry = f"{i}\n{start_time} --> {end_time}\n{text}\n"
            srt_content.append(srt_entry)

        return "\n".join(srt_content)

    def enhance_subtitle(
        self,
        srt_content: str,
        merge_lines: bool = True,
        optimize_text: bool = True,
        rewrite_sentences: bool = True,
        progress_callback=None,
    ) -> tuple[str, Dict]:
        """
        Complete subtitle enhancement pipeline

        Returns:
            tuple: (enhanced_srt_content, stats)
        """
        stats = {
            "original_lines": 0,
            "merged_lines": 0,
            "optimized_lines": 0,
            "rewritten_lines": 0,
        }

        # Parse
        if progress_callback:
            progress_callback(5, "Parsing", "Parsing SRT file...")

        segments = self.parse_srt(srt_content)
        stats["original_lines"] = len(segments)

        if progress_callback:
            progress_callback(
                10,
                "Parsing",
                f"Found {len(segments)} segments",
                stats={"originalLines": len(segments)},
            )

        # Merge
        if merge_lines:
            if progress_callback:
                progress_callback(15, "Merging", "Merging consecutive lines...")

            segments = self.merge_lines(segments)
            stats["merged_lines"] = len(segments)

            if progress_callback:
                progress_callback(
                    30,
                    "Merging",
                    f"Merged to {len(segments)} segments",
                    stats={"mergedLines": len(segments)},
                )
        else:
            stats["merged_lines"] = stats["original_lines"]
            if progress_callback:
                progress_callback(
                    30,
                    "Merging",
                    "Skipping merge step",
                    stats={"mergedLines": len(segments)},
                )

        # Optimize
        if optimize_text:
            if progress_callback:
                progress_callback(35, "Optimizing", "Optimizing text...")

            optimized_segments = []
            batch_size = 20

            for i in range(0, len(segments), batch_size):
                batch = segments[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(segments) + batch_size - 1) // batch_size

                if progress_callback:
                    batch_progress = 35 + ((i / len(segments)) * 25)
                    progress_callback(
                        batch_progress,
                        "Optimizing",
                        f"Optimizing batch {batch_num}/{total_batches}...",
                        stats={"processedLines": i},
                    )

                texts = [seg["text"] for seg in batch]
                optimized_texts = self.optimize_text_batch(texts)

                for seg, opt_text in zip(batch, optimized_texts):
                    optimized_segments.append(
                        {"start": seg["start"], "end": seg["end"], "text": opt_text}
                    )

                # Small delay between batches (removed the long sleep)

            segments = optimized_segments
            stats["optimized_lines"] = len(segments)

            if progress_callback:
                progress_callback(
                    60,
                    "Optimizing",
                    "Optimization complete",
                    stats={"processedLines": len(segments)},
                )
        else:
            stats["optimized_lines"] = stats["merged_lines"]
            if progress_callback:
                progress_callback(60, "Optimizing", "Skipping optimization")

        # Rewrite - FIX: Process in batches instead of groups of 3
        if rewrite_sentences:
            if progress_callback:
                progress_callback(65, "Rewriting", "Rewriting sentences...")

            rewritten_segments = []
            batch_size = 20  # Process 20 segments at a time

            for i in range(0, len(segments), batch_size):
                batch = segments[i : i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(segments) + batch_size - 1) // batch_size

                if progress_callback:
                    rewrite_progress = 65 + ((i / len(segments)) * 30)
                    progress_callback(
                        rewrite_progress,
                        "Rewriting",
                        f"Rewriting batch {batch_num}/{total_batches}...",
                        stats={"processedLines": i},
                    )

                # Get texts from batch
                texts = [seg["text"] for seg in batch]
                
                # Rewrite all texts in batch
                rewritten_texts = self.rewrite_text_batch(texts)

                # Create new segments with rewritten text
                for seg, new_text in zip(batch, rewritten_texts):
                    rewritten_segments.append(
                        {"start": seg["start"], "end": seg["end"], "text": new_text}
                    )

                # Small delay between batches (removed the long sleep)

            segments = rewritten_segments
            stats["rewritten_lines"] = len(segments)

            if progress_callback:
                progress_callback(
                    95,
                    "Rewriting",
                    "Rewriting complete",
                    stats={"processedLines": len(segments)},
                )
        else:
            stats["rewritten_lines"] = stats["optimized_lines"]
            if progress_callback:
                progress_callback(95, "Rewriting", "Skipping rewrite")

        # Finalize
        if progress_callback:
            progress_callback(97, "Finalizing", "Creating enhanced subtitle...")

        enhanced_srt = self.create_srt_content(segments)

        if progress_callback:
            progress_callback(100, "Complete", "Enhancement complete!")

        return enhanced_srt, stats