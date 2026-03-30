FROM python:3.12-slim

WORKDIR /app

# Install system deps (gcc/g++ needed for py-clob-client / web3 native extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
# Install core deps first (always succeed), then optional py-clob-client separately
RUN pip install --no-cache-dir -r requirements.txt || \
    (echo "Full install failed, trying without py-clob-client..." && \
     grep -v py-clob-client requirements.txt > requirements_core.txt && \
     pip install --no-cache-dir -r requirements_core.txt && \
     pip install --no-cache-dir py-clob-client || echo "py-clob-client install failed - paper mode only")

# Copy app
COPY . .

# Create data directory
RUN mkdir -p /app/data

EXPOSE 8000

# Cleanup stale files that may crash startup
RUN echo '#!/bin/sh\n\
# Remove bot.log if it is accidentally a directory\n\
[ -d /app/data/bot.log ] && rm -rf /app/data/bot.log\n\
[ -d /app/bot.log ] && rm -rf /app/bot.log\n\
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1\n\
' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
