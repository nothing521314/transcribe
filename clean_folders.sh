#!/bin/bash

# Script to delete all files in output and uploads folders

echo "Deleting all files in output folder..."
rm -rf output/*

echo "Deleting all files in uploads folder..."
rm -rf uploads/*

echo "Cleanup completed."