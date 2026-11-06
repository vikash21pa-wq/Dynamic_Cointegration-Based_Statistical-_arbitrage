# Production Multi-Architecture Dockerfile for Oracle Cloud Infrastructure (OCI)
# Compatible with both ARM64 (Ampere A1 Always-Free) and AMD64 (Micro Always-Free)
FROM python:3.11-slim-bookworm

# Metadata
LABEL maintainer="Algorithmic Trading Research Team"
LABEL description="Dynamic Cointegration Statistical Arbitrage Autonomous Trading Engine & Dashboard"

# Prevent Python from writing .pyc files and enable unbuffered terminal logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8000

# Install minimal OS build dependencies and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy project source code
COPY . .

# Ensure data and results directories exist
RUN mkdir -p data/raw data/processed results

# Expose Web API and Dashboard port
EXPOSE 8000

# Docker healthcheck querying FastAPI /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch uvicorn web server running autonomous background trading engine
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

