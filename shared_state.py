# shared_state.py
"""
Shared state for the application to avoid circular imports
"""

# Global cancel flags dictionary
cancel_flags = {}

# Global processing tasks dictionary  
processing_tasks = {}

# Task processors dictionary
task_processors = {}

# Task threads dictionary
task_threads = {}

# Translation managers cache
translation_managers = {}