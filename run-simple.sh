#!/bin/bash

case "$1" in
    "start"|"")
        echo "🚀 Starting AI Subtitle Generator..."
        docker-compose -f docker-compose-simple.yml up -d
        echo "✅ Started! Access at http://localhost:5050"
        ;;
    "stop")
        docker-compose -f docker-compose-simple.yml down
        ;;
    "logs")
        docker-compose -f docker-compose-simple.yml logs -f
        ;;
    "rebuild")
        docker-compose -f docker-compose-simple.yml down
        docker-compose -f docker-compose-simple.yml build --no-cache
        docker-compose -f docker-compose-simple.yml up -d
        ;;
    "clean")
        docker-compose -f docker-compose-simple.yml down -v
        docker system prune -f
        ;;
    *)
        echo "Usage: $0 {start|stop|logs|rebuild|clean}"
        ;;
esac
