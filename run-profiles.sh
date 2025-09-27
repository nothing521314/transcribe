#!/bin/bash

# Helper script to run different Docker Compose profiles

case "$1" in
    "basic"|"")
        echo "Starting basic web application..."
        docker-compose -f docker-compose-webapp.yml up -d
        ;;
    "full")
        echo "Starting full stack with all services..."
        docker-compose -f docker-compose-webapp.yml --profile proxy --profile management --profile database up -d
        ;;
    "monitoring")
        echo "Starting with monitoring enabled..."
        docker-compose -f docker-compose-webapp.yml --profile proxy --profile monitoring up -d
        ;;
    "dev")
        echo "Starting development environment..."
        FLASK_ENV=development DEBUG=true docker-compose -f docker-compose-webapp.yml up -d
        ;;
    "stop")
        echo "Stopping all services..."
        docker-compose -f docker-compose-webapp.yml down
        ;;
    "logs")
        echo "Showing logs..."
        docker-compose -f docker-compose-webapp.yml logs -f
        ;;
    "clean")
        echo "Cleaning up containers and volumes..."
        docker-compose -f docker-compose-webapp.yml down -v
        docker system prune -f
        ;;
    *)
        echo "Usage: $0 {basic|full|monitoring|dev|stop|logs|clean}"
        echo ""
        echo "Profiles:"
        echo "  basic      - Just the web application and Redis"
        echo "  full       - Web app + Nginx + File manager + Database"
        echo "  monitoring - Web app + Nginx + Prometheus + Grafana"
        echo "  dev        - Development mode with hot reload"
        echo "  stop       - Stop all services"
        echo "  logs       - Show application logs"
        echo "  clean      - Remove containers and volumes"
        exit 1
        ;;
esac
