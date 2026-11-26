#!/bin/bash

# OpenTenBase AIOps - Quick Start Script
# 快速启动脚本

set -e

echo "============================================"
echo "OpenTenBase AIOps Platform - Quick Start"
echo "============================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found, creating from template..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env file. Please edit it and add your DEEPSEEK_API_KEY"
        echo ""
        echo "Required configuration:"
        echo "  - DEEPSEEK_API_KEY=your_api_key_here"
        echo "  - DB_HOST=otb-node1 (or your OpenTenBase CN host)"
        echo ""
        exit 1
    else
        echo "❌ .env.example not found. Please create .env manually."
        exit 1
    fi
fi

# Check if DEEPSEEK_API_KEY is set
source .env
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "❌ DEEPSEEK_API_KEY is not set in .env file"
    echo "Please edit .env and add your DeepSeek API key"
    exit 1
fi

echo "📋 Configuration check passed"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

echo "🐳 Docker is running"
echo ""

# Check if OpenTenBase network exists
if ! docker network inspect otb-lab-net > /dev/null 2>&1; then
    echo "⚠️  Network 'otb-lab-net' not found"
    echo "Creating network..."
    docker network create otb-lab-net
    echo "✅ Network created"
else
    echo "✅ Network 'otb-lab-net' exists"
fi
echo ""

# Ask user which mode to run
echo "Please select startup mode:"
echo "  1) Development mode (run locally with Python)"
echo "  2) Production mode (Docker Compose)"
echo ""
read -p "Enter choice [1-2]: " choice

case $choice in
    1)
        echo ""
        echo "🚀 Starting in Development mode..."
        echo ""

        # Check if Python is available
        if ! command -v python &> /dev/null; then
            echo "❌ Python not found. Please install Python 3.11+"
            exit 1
        fi

        # Check if dependencies are installed
        if ! python -c "import streamlit" 2> /dev/null; then
            echo "Installing dependencies..."
            pip install -r requirements.txt
        fi

        # Start backend API
        echo "Starting backend API on port 8000..."
        uvicorn backend.app:app --host 0.0.0.0 --port 8000 &
        BACKEND_PID=$!

        sleep 3

        # Start frontend
        echo "Starting frontend on port 8088..."
        export AIOPS_API_URL=http://localhost:8000
        streamlit run frontend/app_redesigned.py --server.port 8088 --server.address 0.0.0.0 &
        FRONTEND_PID=$!

        echo ""
        echo "✅ Services started!"
        echo ""
        echo "📌 Access URLs:"
        echo "   Frontend: http://localhost:8088"
        echo "   API Docs: http://localhost:8000/docs"
        echo ""
        echo "Press Ctrl+C to stop all services"

        # Wait for user interrupt
        trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT
        wait
        ;;

    2)
        echo ""
        echo "🚀 Starting in Production mode (Docker Compose)..."
        echo ""

        # Build images
        echo "Building Docker images..."
        docker-compose build

        # Start services
        echo "Starting services..."
        docker-compose up -d

        echo ""
        echo "✅ Services started!"
        echo ""
        echo "📌 Access URLs:"
        echo "   Frontend: http://localhost:8088"
        echo "   API Docs: http://localhost:8000/docs"
        echo ""
        echo "📊 Check logs: docker-compose logs -f"
        echo "🛑 Stop services: docker-compose down"
        ;;

    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac
