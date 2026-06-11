FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 3004

LABEL org.opencontainers.image.title="ACIP" \
      org.opencontainers.image.description="AI Code Intelligence Platform — call graph traversal, semantic search, and decision memory via MCP" \
      org.opencontainers.image.vendor="ACIP" \
      org.opencontainers.image.source="https://github.com/ColeFlicek/ACIP" \
      org.opencontainers.image.licenses="MIT"

CMD ["python", "-m", "src.server"]
