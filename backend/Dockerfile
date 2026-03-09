# Use Python 3.13 slim image
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Install system dependencies including LaTeX
RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-lang-english \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create temp directory for LaTeX compilation and set permissions
RUN mkdir -p /app/temp /var/lib/celery && \
    addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser && \
    chown -R appuser:appgroup /app/temp /var/lib/celery

# Switch to non-root user
USER appuser

# Expose port 8030
EXPOSE 8030

# Set environment variables
ENV PYTHONPATH=/app
ENV TEMP_DIR=/app/temp
ENV PORT=8030

# Health check — longer start period to allow uvicorn to start + DB connections
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8030/health || exit 1

# Run the application — PORT env var is picked up by settings.PORT (default 8030)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030", "--log-level", "info"]
