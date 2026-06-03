# AI Code Intel (ACIP)

A self-hosted codebase intelligence system that gives Claude Code structured, queryable knowledge of a project — replacing sequential file reads with targeted retrieval.

## Three layers

| Layer | What it captures | Storage |
|---|---|---|
| Call Graph | Function calls, imports, inheritance | SQLite |
| Semantic Embeddings | Conceptual similarity across functions | neo4j vector index |
| Decision Memory | Architectural/design decisions + lineage | Graphiti (neo4j) + SQLite |

## MCP tools

```
index_project(path)
index_changes(file_paths, file_contents)
get_callers(function_name)
get_callees(function_name)
get_impact_radius(function_name, depth)
query_similar_functions(snippet, top_k)
log_decision(type, description, rejected_alternatives, linked_function_ids, parent_decision_id)
get_decision_history(function_name)
query_decisions(query_text)
```

## Stack

- **FastMCP** — Python MCP server on port 3004
- **neo4j 5** — Graphiti backend + vector index for embeddings
- **tree-sitter** — call graph parsing (Python, TypeScript)
- **Configurable embedding model** — OpenAI or Ollama (see below)
- **Claude Haiku** — one-time LLM summary generation per function

## Embedding model configuration

The embedding provider and model are fully configurable via environment variables. No code changes needed to switch.

| Variable | Default | Description |
|---|---|---|
| `EMBEDDING_PROVIDER` | `openai` | `openai` or `ollama` |
| `EMBEDDING_MODEL` | provider default | Model name (see table below) |
| `EMBEDDING_DIM` | inferred | Vector dimensions — inferred for known models, set explicitly for others |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL (only used when provider is `ollama`) |

### Supported models (auto-inferred dimensions)

| Provider | Model | Dimensions |
|---|---|---|
| `openai` | `text-embedding-3-small` *(default)* | 1536 |
| `openai` | `text-embedding-3-large` | 3072 |
| `openai` | `text-embedding-ada-002` | 1536 |
| `ollama` | `nomic-embed-code` *(default)* | 768 |
| `ollama` | `nomic-embed-text` | 768 |
| `ollama` | `mxbai-embed-large` | 1024 |
| `ollama` | `all-minilm` | 384 |

Any model served by Ollama's OpenAI-compatible endpoint works — set `EMBEDDING_DIM` explicitly if your model isn't in the table above.

> **Switching models:** The neo4j vector index is created at a fixed dimension. If you change `EMBEDDING_MODEL` or `EMBEDDING_DIM` after initial setup, you must wipe the existing index first: `docker compose down -v && docker compose up -d`, then re-run `index_project`.

## Quick start

```bash
cp .env.example .env
# Required: NEO4J_PASSWORD, ANTHROPIC_API_KEY
# Required for OpenAI embeddings: OPENAI_API_KEY
# For Ollama: set EMBEDDING_PROVIDER=ollama and ensure Ollama is running
docker compose up -d
```

Then in Claude Code on Agent of Empires, add the MCP server:
```json
{ "mcpServers": { "code-intel": { "url": "http://thehive:3004/mcp" } } }
```

See `CLAUDE.md` for the per-session workflow.
