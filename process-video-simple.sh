#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <video_file_or_url> [languages]"
    echo "Example: $0 video.mp4 vietnamese,chinese,korean"
    exit 1
fi

VIDEO=$1
LANGUAGES=${2:-"vietnamese,chinese,korean"}

echo "📹 Processing: $VIDEO"
echo "🌐 Languages: $LANGUAGES"

# Copy to uploads if local file
if [ -f "$VIDEO" ]; then
    cp "$VIDEO" uploads/videos/
    echo "📁 File copied to uploads/"
fi

echo "🚀 Processing started. Check web interface at http://localhost:5050"
echo "📊 Or check logs: ./run-simple.sh logs"
