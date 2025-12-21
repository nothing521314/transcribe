import re
import time
import logging
import eventlet
from typing import List, Dict, Tuple
import google.generativeai as genai

logger = logging.getLogger(__name__)


class SubtitleEnhancer:
    """Enhanced subtitle processor for merging, optimizing, and rewriting subtitles"""

    def __init__(self, api_key: str):
        """Initialize with Gemini API key"""
        self.api_key = api_key
        genai.configure(api_key=api_key)
        # keep the chosen model; change model name if needed
        self.model = genai.GenerativeModel("gemini-2.0-flash-lite")
        
        # Track total retries across all batches for a task
        self.total_retries_count = {}
        logger.info("SubtitleEnhancer initialized")

    def parse_srt(self, srt_content: str) -> List[Dict]:
        """Parse SRT content into segments"""
        segments = []

        # Normalize line endings and remove BOM if present
        srt_content = srt_content.replace("\r\n", "\n").replace("\r", "\n")
        if srt_content.startswith("\ufeff"):
            srt_content = srt_content[1:]

        # Split by empty lines (one or more consecutive newlines)
        blocks = re.split(r"\n\s*\n", srt_content.strip())

        logger.info(f"Found {len(blocks)} blocks in SRT content")

        for idx, block in enumerate(blocks):
            if not block.strip():
                continue

            lines = [line.strip() for line in block.strip().split("\n") if line.strip()]

            if idx < 3:
                logger.debug(f"Block {idx}: {len(lines)} lines - {lines}")

            # SRT format: line 0 = number, line 1 = timing, line 2+ = text
            if len(lines) >= 2:
                # if there's only an index and timing but no text, skip
                # handle formats where index might be absent (rare) by checking timing line
                # Identify timing line (first line that contains --> or -->)
                timing_idx = None
                for i_l, l in enumerate(lines[:2]):  # usually at index 1, but be safe
                    if "-->" in l or " --> " in l:
                        timing_idx = i_l
                        break

                if timing_idx is None:
                    # try to find any timing-like line in first 3 lines
                    for i_l, l in enumerate(lines[:3]):
                        if "-->" in l or " --> " in l:
                            timing_idx = i_l
                            break

                if timing_idx is None:
                    logger.warning(f"Skipping block {idx}: no timing line found - {lines[:3]}")
                    continue

                # text lines are those after timing line
                if timing_idx + 1 >= len(lines):
                    logger.warning(f"Skipping block {idx}: timing but no text - {lines}")
                    continue

                time_line = lines[timing_idx]

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

                try:
                    start = self._parse_srt_time(times[0])
                    end = self._parse_srt_time(times[1])
                except Exception as e:
                    logger.warning(f"Failed parsing times in block {idx}: {e}")
                    continue

                # Validate times
                if start < 0 or end < 0 or end <= start:
                    logger.warning(f"Invalid times in block {idx}: start={start}, end={end}")
                    continue

                # Get text (lines after timing)
                text_lines = lines[timing_idx + 1 :]
                text = " ".join(text_lines).strip()

                if not text:
                    logger.warning(f"Empty text in block {idx}")
                    continue

                segments.append({"start": start, "end": end, "text": text})

            else:
                if idx < 10:
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
        if seconds < 0:
            seconds = 0.0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs_int = int(seconds) % 60
        millis = int(round((seconds - int(seconds)) * 1000))
        # ensure millis in 0..999
        millis = max(0, min(999, millis))
        return f"{hours:02d}:{minutes:02d}:{secs_int:02d},{millis:03d}"

    def merge_lines(self, segments: List[Dict]) -> List[Dict]:
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

    def optimize_text_batch(self, texts: List[str], cancel_flag: Dict = None, 
                            task_id: str = None, progress_callback = None,
                            progress_callback_offset: int = 0) -> List[str]:
        """Optimize text batch with Gemini"""
        try:
            if cancel_flag is None:
                from shared_state import cancel_flags
                cancel_flag = cancel_flags
            # CHECK BEFORE API CALL
            if cancel_flag and task_id and cancel_flag.get(task_id):
                logger.info(f"Optimization cancelled before API call")
                return texts
        
            # Build prompt carefully
            original_lines = "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])
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
{original_lines}

Return optimized texts (one per line):"""

            response_text = self._call_gemini_with_retry(
                prompt, 
                temperature=0.3, 
                cancel_flag=cancel_flag, 
                task_id=task_id,
                progress_callback=progress_callback,
                progress_callback_offset=progress_callback_offset
            )
            
            # CHECK AFTER API CALL
            if cancel_flag and task_id and cancel_flag.get(task_id):
                logger.info(f"Optimization cancelled after API call")
                return texts

            # Parse numbered results robustly
            optimized = self._parse_numbered_response(response_text, expected=len(texts))

            # Fallback: if parse fails or counts mismatch, return original texts
            if not optimized or len(optimized) != len(texts):
                logger.warning("Optimization parsing mismatch or empty — falling back to original texts or best-effort mapping.")
                # Try to at least return same-length list by mapping lines
                while len(optimized) < len(texts):
                    optimized.append(texts[len(optimized)])
                return optimized[: len(texts)]

            logger.info(f"Optimized {len(optimized)} texts from batch of {len(texts)}")
            return optimized[: len(texts)]

        except Exception as e:
            logger.error(f"Text optimization error: {e}")
            return texts

    def rewrite_text_batch(self, texts: List[str], cancel_flag: Dict = None, 
                           task_id: str = None, progress_callback = None,
                           progress_callback_offset: int = 0) -> List[str]:
        """Rewrite a batch of texts with different structure but same meaning"""
        try:
            # CHECK BEFORE API CALL
            if cancel_flag and task_id and cancel_flag.get(task_id):
                logger.info(f"Rewrite cancelled before API call")
                return texts

            original_lines = "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])
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
{original_lines}

Return rewritten texts (one per line):"""

            response_text = self._call_gemini_with_retry(
                prompt,
                temperature=0.7,
                max_retries=3,
                cancel_flag=cancel_flag,
                task_id=task_id,
                progress_callback=progress_callback,
                progress_callback_offset=progress_callback_offset
            )

            # CHECK AFTER API CALL
            if cancel_flag and task_id and cancel_flag.get(task_id):
                logger.info(f"Rewrite cancelled after API call")
                return texts

            rewritten = self._parse_numbered_response(response_text, expected=len(texts))

            if not rewritten or len(rewritten) != len(texts):
                logger.warning("Rewrite parsing mismatch or empty — falling back to original texts or best-effort mapping.")
                while len(rewritten) < len(texts):
                    rewritten.append(texts[len(rewritten)])
                return rewritten[: len(texts)]

            logger.info(f"Rewritten {len(rewritten)} texts from batch of {len(texts)}")
            return rewritten[: len(texts)]

        except Exception as e:
            logger.error(f"Text rewrite error: {e}")
            return texts

    def _parse_numbered_response(self, response_text: str, expected: int) -> List[str]:
        """Generic parser for responses in numbered form '1. text' ..."""
        if not response_text:
            return []

        items: List[str] = []
        current_num = 0
        current_text = ""

        for raw_line in response_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = re.match(r"^(\d+)\.\s*(.*)$", line)
            if match:
                # save previous
                if current_text != "" and current_num > 0:
                    items.append(current_text.strip())
                current_num = int(match.group(1))
                current_text = match.group(2).strip()
            else:
                # continuation line (append)
                if current_num > 0:
                    current_text += " " + line

        if current_text != "" and current_num > 0:
            items.append(current_text.strip())

        # If parser produced more than expected, truncate; if less, keep as-is (caller will pad)
        if len(items) > expected:
            items = items[:expected]

        return items

    def _call_gemini_with_retry(self, prompt: str, temperature: float = 0.3, 
                                max_retries: int = 3, cancel_flag: Dict = None, 
                                task_id: str = None, progress_callback = None,
                                progress_callback_offset: int = 0) -> str:
        """Call Gemini API with retry logic for rate limits"""
        # Initialize retry counter for this task if not exists
        if task_id and task_id not in self.total_retries_count:
            self.total_retries_count[task_id] = 0

        for attempt in range(max_retries):
            if cancel_flag and task_id and cancel_flag.get(task_id):
                logger.info(f"Gemini call cancelled at attempt {attempt+1}")
                raise InterruptedError("Task cancelled")

            if task_id and self.total_retries_count[task_id] >= 3:
                logger.error(f"Total retry limit (3) reached across all batches for task {task_id}")
                if cancel_flag and task_id:
                    cancel_flag[task_id] = True
                if progress_callback:
                    progress_callback(
                        progress_callback_offset,
                        "Failed",
                        f"Task cancelled: Maximum retry limit (3) reached across all batches"
                    )
                raise RuntimeError(f"Task {task_id} cancelled after 3 total retries across batches")

            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=temperature,
                        max_output_tokens=2000,
                    ),
                )
                # Success - reset retry count for this task
                if task_id:
                    self.total_retries_count[task_id] = 0
                return self._extract_response_text(response)

            except Exception as e:
                error_msg = str(e)
                
                # Increment total retry counter
                if task_id:
                    self.total_retries_count[task_id] += 1
                    total_retries = self.total_retries_count[task_id]
                    logger.warning(f"Gemini call failed. Total retries for task: {total_retries}/3")
                    
                    # Check if we've hit the global retry limit
                    if total_retries >= 3:
                        logger.error(f"Total retry limit (3) reached for task {task_id}. Cancelling entire task.")
                        if cancel_flag:
                            cancel_flag[task_id] = True
                        if progress_callback:
                            progress_callback(
                                progress_callback_offset,
                                "Failed", 
                                f"Task cancelled after 3 total API retry attempts.\nError: {error_msg.split('.')[0]}"
                            )
                        raise RuntimeError(f"Task {task_id} cancelled after 3 total retries: {error_msg}")
                
                logger.warning(f"Gemini call attempt {attempt+1}/{max_retries} failed (total task retries: {self.total_retries_count.get(task_id, 0)}/3): {error_msg}")

                # Check rate-limit-like messages
                if "429" in error_msg or "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    # Try to extract seconds
                    retry_match = re.search(r"(\d+)\s*seconds", error_msg)
                    if retry_match:
                        wait_time = int(retry_match.group(1)) + 2
                    else:
                        wait_time = 30  # default shorter wait

                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limit detected. Waiting {wait_time}s before retrying...")
                        if progress_callback:
                            remaining_global = 3 - self.total_retries_count.get(task_id, 0)
                            progress_callback(
                                progress_callback_offset,
                                "Waiting",
                                f"Rate limit hit (total retries: {self.total_retries_count.get(task_id, 0)}/3)\nWaiting {wait_time}s before retry..."
                            )
                        for _ in range(wait_time):
                            if cancel_flag and task_id and cancel_flag.get(task_id):
                                logger.info("Cancelled during rate limit wait")
                                if progress_callback:
                                    progress_callback(
                                        progress_callback_offset,
                                        "Cancelled",
                                        "Cancelled during rate limit wait"
                                    )
                                raise InterruptedError("Task cancelled")
                            time.sleep(1)
                        continue
                else:
                    # For non-rate-limit errors, still check total retries
                    if attempt < max_retries - 1 and (not task_id or self.total_retries_count.get(task_id, 0) < 3):
                        if progress_callback:
                            remaining_global = 3 - self.total_retries_count.get(task_id, 0)
                            progress_callback(
                                progress_callback_offset,
                                "Error",
                                f"API error (total retries: {self.total_retries_count.get(task_id, 0)}/3): {error_msg.split('.')[0]}"
                            )
                        time.sleep(2)
                        continue
        return ""

    def _extract_response_text(self, response) -> str:
        """Safely extract text from Gemini response"""
        try:
            # Prefer 'candidates' path (older SDK output)
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                content = getattr(candidate, "content", None)
                if content and hasattr(content, "parts"):
                    parts = []
                    for p in content.parts:
                        text = getattr(p, "text", "")
                        if text:
                            parts.append(text)
                    if parts:
                        return "\n".join(parts)

            # Newer responses might have "output" attribute or top-level text
            if hasattr(response, "output") and isinstance(response.output, list):
                parts = []
                for el in response.output:
                    text = el.get("content", {}).get("text") if isinstance(el, dict) else None
                    if text:
                        parts.append(text)
                if parts:
                    return "\n".join(parts)

            # Fallback: try str()
            as_str = str(response)
            return as_str

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
        cancel_flag: Dict = None,
        task_id: str = None
    ) -> Tuple[str, Dict]:
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

        try:

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
                    if cancel_flag and cancel_flag.get("cancelled", False):
                        logger.warning("Enhancement cancelled during optimize step")
                        return "", {**stats, "cancelled": True}

                    batch = segments[i : i + batch_size]
                    batch_num = i // batch_size + 1
                    total_batches = (len(segments) + batch_size - 1) // batch_size

                    if progress_callback:
                        batch_progress = 35 + ((i / max(1, len(segments))) * 25)
                        progress_callback(
                            batch_progress,
                            "Optimizing",
                            f"Optimizing batch {batch_num}/{total_batches}...",
                            stats={"processedLines": i},
                        )

                    texts = [seg["text"] for seg in batch]
                    optimized_texts = self.optimize_text_batch(
                        texts,
                        cancel_flag=cancel_flag,
                        task_id=task_id,
                        progress_callback=progress_callback,
                        progress_callback_offset=batch_progress
                    )

                    for seg, opt_text in zip(batch, optimized_texts):
                        optimized_segments.append(
                            {"start": seg["start"], "end": seg["end"], "text": opt_text}
                        )

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

            # Rewrite - only 1 out of each 3 sentences (i.e., 3rd, 6th, 9th, ...)
            if rewrite_sentences:
                if progress_callback:
                    progress_callback(65, "Rewriting", "Rewriting sentences...")

                # Get indices of sentences to rewrite
                rewrite_indices = [i for i in range(len(segments)) if i % 3 == 0]
                texts_to_rewrite = [segments[i]["text"] for i in rewrite_indices]

                rewritten_texts = []
                batch_size = 20
                total_batches = (len(texts_to_rewrite) + batch_size - 1) // batch_size

                for b in range(0, len(texts_to_rewrite), batch_size):
                    if cancel_flag and cancel_flag.get("cancelled", False):
                        logger.warning("Enhancement cancelled during rewrite step")
                        return "", {**stats, "cancelled": True}
                    batch = texts_to_rewrite[b:b+batch_size]
                    batch_num = b // batch_size + 1
                    batch_progress = 65 + ((b / len(texts_to_rewrite)) * 30)

                    if progress_callback:
                        progress_callback(
                            batch_progress,
                            "Rewriting",
                            f"Rewriting batch {batch_num}/{total_batches}...",
                            stats={"processedLines": b},
                        )

                    rewritten_batch = self.rewrite_text_batch(
                        batch,
                        cancel_flag=cancel_flag,
                        task_id=task_id,
                        progress_callback=progress_callback,
                        progress_callback_offset=batch_progress
                    )
                    rewritten_texts.extend(rewritten_batch)

                # Place rewritten texts back into rewritten_segments at right positions
                for idx, new_text in zip(rewrite_indices, rewritten_texts):
                    segments[idx]["text"] = new_text

                stats["rewritten_lines"] = len(rewrite_indices)

                if progress_callback:
                    progress_callback(
                        95,
                        "Rewriting",
                        f"Rewriting complete ({len(rewrite_indices)} lines rewritten)",
                        stats={"processedLines": len(rewrite_indices)},
                    )
            else:
                stats["rewritten_lines"] = 0
                if progress_callback:
                    progress_callback(95, "Rewriting", "Skipping rewrite")


            # Finalize
            if progress_callback:
                progress_callback(97, "Finalizing", "Creating enhanced subtitle...")

            enhanced_srt = self.create_srt_content(segments)

            if progress_callback:
                progress_callback(100, "Complete", "Enhancement complete!")

            return enhanced_srt, stats
        finally:
            # Clean up retry counter for this task
            if task_id and task_id in self.total_retries_count:
                del self.total_retries_count[task_id]
    
    def strip_timelines_one_line(self, srt_content: str) -> str:
        """
		Remove timeline and index from SRT, return pure text in one single line.
		"""
        texts = []
        for line in srt_content.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.match(r"^\d+$", line):  # index
                continue
            if re.match(r"^\d{2}:\d{2}:\d{2},\d{3}", line):  # timeline
                continue
            texts.append(line)
        return " ".join(texts)
