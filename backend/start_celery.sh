#!/bin/bash

# Start Celery workers for Phase 8 development
# Make sure Redis is running before starting workers

echo "Starting Celery workers for Latexy Phase 8..."

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export PYTHONPATH=$(pwd)

# Start Celery worker in the background
echo "Starting Celery worker..."
celery -A app.core.celery_app worker --loglevel=info --concurrency=4 --queues=latex,llm,email,cleanup,ats &
WORKER_PID=$!

# Start Celery beat for scheduled tasks
echo "Starting Celery beat..."
celery -A app.core.celery_app beat --loglevel=info &
BEAT_PID=$!

# Start Flower for monitoring (optional)
echo "Starting Flower monitoring..."
celery -A app.core.celery_app flower --port=5555 &
FLOWER_PID=$!

echo "Celery services started:"
echo "  Worker PID: $WORKER_PID"
echo "  Beat PID: $BEAT_PID"
echo "  Flower PID: $FLOWER_PID"
echo ""
echo "Access Flower monitoring at: http://localhost:5555"
echo ""
echo "Press Ctrl+C to stop all services..."

# Function to cleanup on exit
cleanup() {
    echo "Stopping Celery services..."
    kill $WORKER_PID $BEAT_PID $FLOWER_PID 2>/dev/null
    wait
    echo "All services stopped."
}

# Set trap to cleanup on script exit
trap cleanup EXIT

# Wait for user interrupt
wait
