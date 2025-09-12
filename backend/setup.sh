# =====================================================
# FILE: setup.sh - Development Setup Script
# =====================================================

#!/bin/bash
set -e

echo "🚀 Setting up ATS Resume Optimizer - Phase 1"

# Check if Python 3.11+ is installed
python_version=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
if [[ $(echo "$python_version >= 3.11" | bc) -eq 0 ]]; then
    echo "❌ Python 3.11 or higher is required. Current version: $python_version"
    exit 1
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install development dependencies
echo "📦 Installing development dependencies..."
pip install pytest pytest-asyncio httpx

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is required but not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is required but not installed. Please install Docker Compose first."
    exit 1
fi

# Create logs directory
mkdir -p logs

# Copy environment file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📋 Created .env file from template"
fi

echo "✅ Setup completed successfully!"
echo ""
echo "🚀 To start the development server:"
echo "   source venv/bin/activate"
echo "   python main.py"
echo ""
echo "🐳 To start with Docker:"
echo "   docker-compose up --build"
echo ""
echo "🧪 To run tests:"
echo "   source venv/bin/activate"
echo "   pytest"