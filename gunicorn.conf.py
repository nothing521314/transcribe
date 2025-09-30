import os

# Server socket
bind = "0.0.0.0:5050"
backlog = 2048

# Worker processes
workers = int(os.environ.get('WORKERS', 2))
worker_class = 'gevent'
worker_connections = 1000
timeout = int(os.environ.get('TIMEOUT', 300))
keepalive = 2

# Restart workers
max_requests = 1000
max_requests_jitter = 100

# Logging
errorlog = '-'
loglevel = 'info'
accesslog = '-'

# Process naming
proc_name = 'subtitle-webapp'

# Server mechanics
daemon = False
preload_app = True
