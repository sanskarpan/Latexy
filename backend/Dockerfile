# Use the canonical production/development Python version.
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies including LaTeX
RUN apt-get update && apt-get install -y \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-xetex \
    texlive-luatex \
    texlive-lang-chinese \
    texlive-lang-japanese \
    texlive-lang-korean \
    texlive-lang-arabic \
    texlive-lang-european \
    texlive-lang-greek \
    fonts-noto-cjk \
    fonts-noto-core \
    fonts-texgyre \
    texlive-lang-english \
    fonts-lohit-deva \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy the generated, hash-verified lock first for better caching.
COPY scripts/warm_tex_cache.sh /usr/local/bin/latexy-warm-tex-cache
RUN sh /usr/local/bin/latexy-warm-tex-cache
COPY scripts/build_trusted_render_formats.py /opt/latexy-format-build/scripts/build_trusted_render_formats.py
COPY app/services/render_engine/managed_preamble.py /opt/latexy-format-build/app/services/render_engine/managed_preamble.py
RUN python /opt/latexy-format-build/scripts/build_trusted_render_formats.py
COPY scripts/write_renderer_fingerprint.py /usr/local/bin/latexy-write-renderer-fingerprint.py
RUN python /usr/local/bin/latexy-write-renderer-fingerprint.py
ENV TEXMFCACHE=/var/lib/texmf

COPY requirements-dev.lock .

# Install the reproducible development/test environment used by this image.
RUN pip install --no-cache-dir --require-hashes -r requirements-dev.lock

# Copy the application code
COPY . .

# Create temp directory for LaTeX compilation and set permissions
RUN mkdir -p /app/temp /var/lib/celery /pycache && \
    addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup --no-create-home appuser && \
    chown -R appuser:appgroup /app/temp /var/lib/celery /pycache

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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8030", "--log-level", "info", "--ws-max-size", "524288"]
