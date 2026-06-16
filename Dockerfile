FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# SCIP indexers — compiler-accurate call graphs (primary structural layer).
# scip-python was previously broken: pip install scip-python does not exist on
# PyPI. The correct package is @sourcegraph/scip-python on npm.
# scip CLI converts .scip binary → JSON for ScipImporter.
RUN npm install -g @sourcegraph/scip-python @sourcegraph/scip 2>/dev/null || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY scripts/ ./scripts/
COPY schema.sql .

EXPOSE 3004

LABEL org.opencontainers.image.title="ACIP" \
      org.opencontainers.image.description="AI Code Intelligence Platform — call graph traversal, semantic search, and decision memory via MCP" \
      org.opencontainers.image.vendor="ACIP" \
      org.opencontainers.image.source="https://github.com/ColeFlicek/ACIP" \
      org.opencontainers.image.licenses="MIT"

CMD ["python", "-m", "src.server"]
