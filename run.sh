#!/bin/bash

case "$1" in
    "start"|"")
        echo "Starting services..."
        docker-compose up -d
        echo "✓ Started! Access at:"
        echo "  Web App: http://localhost:5050"
        echo "  File Browser: http://localhost:8080"
        ;;
    "stop")
        docker-compose down
        ;;
    "logs")
        docker-compose logs -f subtitle-webapp
        ;;
    "restart")
        docker-compose restart
        ;;
    "rebuild")
        docker-compose down
        docker-compose build --no-cache
        docker-compose up -d
        ;;
    "clean")
        docker-compose down -v
        docker system prune -f
        ;;
    "status")
        docker-compose ps
        ;;
    *)
        echo "Usage: $0 {start|stop|logs|restart|rebuild|clean|status}"
        ;;
esac
