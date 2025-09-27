#!/bin/bash

# Quick video processing script

if [ $# -eq 0 ]; then
    echo "Usage: $0 <video_file_or_url> [languages]"
    echo "Example: $0 video.mp4 vietnamese,chinese,korean"
    echo "Example: $0 https://youtube.com/watch?v=abc123"
    exit 1
fi

VIDEO=$1
LANGUAGES=${2:-"vietnamese,chinese,korean,french"}

echo "Processing: $VIDEO"
echo "Languages: $LANGUAGES"

# Copy to uploads if it's a local file
if [ -f "$VIDEO" ]; then
    echo "Copying file to uploads directory..."
    cp "$VIDEO" uploads/videos/
    VIDEO="uploads/videos/$(basename "$VIDEO")"
fi

# Call the web app API or use direct processing
curl -X POST http://localhost:5050/upload \
    -F "video_url=$VIDEO" \
    -F "languages=$LANGUAGES"

echo "Processing started. Check the web interface at http://localhost:5050"
