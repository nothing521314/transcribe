# routes/enhance_subtitle.py

import os
import time
import hashlib
import logging
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file
from subtitle_enhancer import SubtitleEnhancer

logger = logging.getLogger(__name__)

# Create blueprint
enhance_subtitle_bp = Blueprint('enhance_subtitle', __name__)


def init_enhance_routes(app, socketio, processing_tasks, cancel_flags, OUTPUT_FOLDER, cleanup_task):
    """Initialize enhancement routes with dependencies"""
    
    @enhance_subtitle_bp.route("/enhance_subtitle", methods=["GET"])
    def enhance_subtitle_page():
        """Page for enhancing English subtitles"""
        return render_template("enhance_subtitle.html")
    
    @enhance_subtitle_bp.route("/api/enhance_subtitle", methods=["POST"])
    def enhance_subtitle_api():
        """API endpoint to enhance subtitle"""
        try:
            srt_content = request.form.get("srt_content")
            api_key = request.form.get("api_key")
            merge_lines = request.form.get("merge_lines", "true").lower() == "true"
            optimize_text = request.form.get("optimize_text", "true").lower() == "true"
            rewrite_sentences = request.form.get("rewrite_sentences", "true").lower() == "true"
            
            if not srt_content or not api_key:
                return jsonify({
                    "success": False,
                    "message": "SRT content and API key are required"
                }), 400
            
            # Generate task ID
            task_id = hashlib.md5(
                f"{datetime.now().isoformat()}{srt_content[:100]}".encode()
            ).hexdigest()
            
            # Initialize task
            processing_tasks[task_id] = {
                "status": "processing",
                "start_time": datetime.now(),
                "type": "enhance_subtitle"
            }
            cancel_flags[task_id] = False
            
            # Start enhancement in background
            socketio.start_background_task(
                enhance_subtitle_task,
                task_id,
                srt_content,
                api_key,
                merge_lines,
                optimize_text,
                rewrite_sentences,
                socketio,
                processing_tasks,
                cancel_flags,
                OUTPUT_FOLDER,
                cleanup_task
            )
            
            return jsonify({
                "success": True,
                "task_id": task_id,
                "message": "Enhancement started"
            })
            
        except Exception as e:
            logger.error(f"Enhance subtitle API error: {e}")
            return jsonify({
                "success": False,
                "message": f"Error: {str(e)}"
            }), 500
    
    @enhance_subtitle_bp.route("/download_enhanced/<task_id>")
    def download_enhanced_subtitle(task_id):
        """Download enhanced subtitle file"""
        try:
            if task_id not in processing_tasks:
                return jsonify({"error": "Task not found"}), 404
            
            task = processing_tasks[task_id]
            
            if task["status"] != "completed":
                return jsonify({"error": "Enhancement not completed"}), 400
            
            output_path = task.get("output_file")
            if not output_path or not os.path.exists(output_path):
                return jsonify({"error": "File not found"}), 404
            
            return send_file(
                output_path,
                as_attachment=True,
                download_name=os.path.basename(output_path)
            )
            
        except Exception as e:
            logger.error(f"Download enhanced subtitle error: {e}")
            return jsonify({"error": "Download failed"}), 500
    
    # Register blueprint
    app.register_blueprint(enhance_subtitle_bp)
    logger.info("Enhancement routes registered")


def enhance_subtitle_task(task_id, srt_content, api_key, merge_lines, 
                         optimize_text, rewrite_sentences, socketio,
                         processing_tasks, cancel_flags, OUTPUT_FOLDER,
                         cleanup_task):
    """Background task for subtitle enhancement"""
    try:
        output_dir = os.path.join(OUTPUT_FOLDER, "enhanced_subtitles")
        os.makedirs(output_dir, exist_ok=True)
        
        def emit_progress(progress, step, message, **kwargs):
            """Emit progress update"""
            if cancel_flags.get(task_id):
                raise InterruptedError("Enhancement cancelled")
            
            socketio.emit("enhance_progress", {
                "task_id": task_id,
                "progress": progress,
                "step": step,
                "message": message,
                "status": "processing",
                **kwargs
            }, room=task_id)
            socketio.sleep(0)
        
        # Initialize enhancer
        emit_progress(2, "Initializing", "Initializing enhancement engine...")
        enhancer = SubtitleEnhancer(api_key)
        
        # Enhance subtitle with progress callback
        enhanced_srt, stats = enhancer.enhance_subtitle(
            srt_content,
            merge_lines=merge_lines,
            optimize_text=optimize_text,
            rewrite_sentences=rewrite_sentences,
            progress_callback=emit_progress,
            cancel_flag=cancel_flags
        )
        
        # Save output file
        output_filename = f"enhanced_{int(time.time())}.srt"
        output_path = os.path.join(output_dir, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(enhanced_srt)
        
        # Update task
        processing_tasks[task_id]["status"] = "completed"
        processing_tasks[task_id]["output_file"] = output_path
        processing_tasks[task_id]["stats"] = stats
        
        # Final emit
        socketio.emit("enhance_progress", {
            "task_id": task_id,
            "progress": 100,
            "step": "Complete",
            "message": "Enhancement completed successfully!",
            "status": "completed",
            "download_url": f"/download_enhanced/{task_id}",
            "stats": {
                'originalLines': stats['original_lines'],
                'mergedLines': stats['merged_lines'],
                'processedLines': stats['rewritten_lines']
            }
        }, room=task_id)
        
        logger.info(f"Subtitle enhancement completed: {output_filename}")
        logger.info(f"Stats: {stats}")
        
    except InterruptedError:
        logger.info(f"Subtitle enhancement cancelled: {task_id}")
        processing_tasks[task_id]["status"] = "cancelled"
        socketio.emit("enhance_progress", {
            "task_id": task_id,
            "status": "cancelled",
            "message": "Enhancement was cancelled"
        }, room=task_id)
        
    except Exception as e:
        logger.error(f"Subtitle enhancement error: {e}", exc_info=True)
        processing_tasks[task_id]["status"] = "error"
        socketio.emit("enhance_progress", {
            "task_id": task_id,
            "status": "error",
            "message": f"Enhancement failed: {str(e)}"
        }, room=task_id)
    finally:
        cleanup_task(task_id)