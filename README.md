# Confucius Code Agent (CCA)

An AI coding agent that runs as an **Agent-as-a-Model** HTTP server. Send it OpenAI-compatible `/v1/chat/completions` requests, and it runs a full agent loop internally — reading files, executing commands, editing code, searching the web, and managing long-term memory — then returns the result as a standard chat completion.

Built on [Meta/Harvard's Confucius framework](https://arxiv.org/abs/2512.10398), extended with expert routing, user awareness, code intelligence, and optimized for local inference on NVIDIA DGX Spark (or any vLLM-compatible setup).

```
┌─────────────────────────────────────────────────────────────────────┐
│  Client (any OpenAI-compatible tool)                                │
│  Continue.dev, Cursor, curl, Python SDK, ...                        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ POST /v1/chat/completions
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CCA Server (:8500)                                                 │
│                                                                     │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐   │
│  │ Expert       │───>│ Agent Loop (DualModelOrchestrator)       │   │
│  │ Router       │    │                                          │   │
│  │ (classify    │    │  Plan → Execute → Observe → Repeat       │   │
│  │  request)    │    │                                          │   │
│  └─────────────┘    │  Tools: bash, file edit, web search,     │   │
│                      │  code review, test gen, memory, ...      │   │
│                      └──────────────────────────────────────────┘   │
│                                     │                               │
│                                     ▼                               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Backends: vLLM (local), Redis, Qdrant, Embedding, SearXNG   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Why Agent-as-a-Model?

Most AI coding tools require specific IDE plugins or CLI clients. CCA takes a different approach: it exposes the full agent as a standard OpenAI-compatible model endpoint.

This means **any tool that can talk to the OpenAI API can use CCA** — Continue.dev, Cursor, custom scripts, or a simple `curl`. The agent loop (planning, tool use, iteration) happens server-side. The client just sees a chat completion response.

**What happens when you send a message:**
1. Expert Router classifies your request (coder, infrastructure, search, etc.)
2. The appropriate tool set is loaded for that expert type
3. The agent plans, executes tools, and iterates until the task is done
4. You get back a single coherent response (streaming or non-streaming)

## Features

- **OpenAI-compatible API** — drop-in replacement for `/v1/chat/completions` and `/v1/models`
- **Expert routing** — classifies requests and loads the right tools (code, infrastructure, search, user management)
- **Two-LLM architecture** — large model (coder) + small model (note-taker) for cost-efficient operation
- **User awareness** — identifies users across sessions, stores preferences and facts in Qdrant
- **Code intelligence** — workspace indexing, semantic code search, knowledge graph (Memgraph)
- **Long-term memory** — note-taker observes every session and persists insights to vector DB
- **Web search** — SearXNG integration for real-time information
- **Phoenix tracing** — full OpenTelemetry observability for every agent run
- **TOML config** — switch between local vLLM and cloud providers (Azure, Bedrock, Google) with a config change
- **Docker-first** — single `docker compose up` to run the whole stack

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/seli-equinix/confucius-code-agent.git
cd confucius-code-agent

# Copy example configs
cp config.toml.example config.toml
cp infrastructure.toml.example infrastructure.toml
cp .env.example .env

# Edit config.toml with your vLLM endpoint, Redis, Qdrant URLs
# Edit .env with your secrets (Redis password, API keys)
```

### 2. Configure your LLM backend

CCA needs an OpenAI-compatible LLM endpoint. Edit `config.toml`:

```toml
[active]
coder = "local"        # Use local vLLM
note_taker = "local"   # Use local small model

[providers.local.coder]
model = "/models/Qwen3-32B"          # Your model name
provider = "openai"
base_url = "http://your-vllm-host:8000/v1"
api_key_env = "OPENAI_API_KEY"
temperature = 0.3

[providers.local.note_taker]
model = "/models/Qwen3-8B"
provider = "openai"
base_url = "http://your-notetaker-host:8400/v1"
api_key_env = "OPENAI_API_KEY"
temperature = 0.3
```

Or use cloud providers:

```toml
[active]
coder = "cloud"
note_taker = "cloud"

[providers.cloud.coder]
model = "gpt-4o"
provider = "azure"

[providers.cloud.note_taker]
model = "claude-sonnet-4-5"
provider = "bedrock"
```

### 3. Run with Docker

```bash
docker compose -f cca-compose.yml up -d cca
```

### 4. Test it

```bash
# Health check
curl http://localhost:8500/health

# List models
curl http://localhost:8500/v1/models

# Send a coding task
curl -X POST http://localhost:8500/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"cca","messages":[{"role":"user","content":"List all Python files in /workspace and summarize what they do"}]}'

# Stream a response
curl -X POST http://localhost:8500/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"cca","messages":[{"role":"user","content":"Hello, what can you help me with?"}],"stream":true}'
```

## Architecture

### Expert Types

The router classifies each request and loads the appropriate tool set:

| Expert | Tools | Use Case |
|--------|-------|----------|
| **coder** | file edit, bash, git, planning, memory, web | Code editing, debugging, refactoring |
| **infrastructure** | docker, SSH, systemctl, networking, memory | DevOps, deployments, cluster management |
| **search** | web search, file search, memory | Research, documentation lookup |
| **planner** | planning, memory | Multi-step task decomposition |
| **user** | user profile tools | User identification, preferences |
| **direct** | *(none — immediate answer)* | Simple Q&A, no agent loop needed |

### Two-LLM Architecture

CCA uses two models working together:

- **Coder** (large model) — handles the actual agent work: planning, tool calling, code generation
- **Note-taker** (small model) — observes every session in the background, extracts insights, and stores them in Qdrant for future context enrichment

This means CCA learns from past sessions and gets better at helping you over time.

### Backend Services

| Service | Purpose | Required |
|---------|---------|----------|
| **vLLM** | LLM inference (coder + note-taker) | Yes |
| **Redis** | Session state, critical facts, trajectories | Yes |
| **Qdrant** | User profiles, code search, long-term notes | Yes |
| **Embedding server** | Semantic search (Qwen3-Embedding) | Yes |
| **SearXNG** | Web search | Optional |
| **Memgraph** | Code knowledge graph | Optional |
| **Phoenix** | Trace visualization | Optional |

## Configuration

All configuration lives in three files:

| File | Purpose | Tracked by Git |
|------|---------|----------------|
| `config.toml` | Models, providers, service URLs, router settings | No (use `config.toml.example`) |
| `infrastructure.toml` | Cluster topology for infra expert (optional) | No (use `infrastructure.toml.example`) |
| `.env` | Secrets: Redis password, API keys, GitLab tokens | No (use `.env.example`) |

### Switching Providers

Change `[active]` in `config.toml` — no code changes needed:

```toml
[active]
coder = "local"    # → routes to your vLLM endpoint
# coder = "cloud"  # → routes to Azure/Bedrock/Google
```

### Environment Variables

Set in `.env` (see `.env.example` for full list):

```env
OPENAI_API_KEY=dummy                    # "dummy" for local vLLM
REDIS_URL=redis://:password@host:6379/0
CCA_WORKSPACE=/path/to/your/code
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat (streaming + non-streaming) |
| `GET` | `/v1/models` | List served model |
| `GET` | `/health` | Health check |
| `POST` | `/route/test` | Test expert router classification |
| `GET` | `/users` | List known user profiles |
| `GET` | `/sessions` | List active agent sessions |
| `GET` | `/stats` | Diagnostic statistics |

## Development

### Local Development (source-mounted)

```bash
# Start with source code mounted (no rebuild for code changes)
docker compose -f cca-compose.yml --profile dev up -d cca-dev
```

### Without Docker

```bash
conda create -n confucius python=3.12 -y
conda activate confucius
pip install -r requirements.txt

# Run the server
python -m confucius --port 8500
```

### Project Structure

```
confucius/
├── __main__.py              # Entry point (confucius --port 8500)
├── core/                    # Config, LLM managers, tracing, memory
├── orchestrator/            # Agent loop, extension pipeline
│   └── extensions/          # Tools: file edit, bash, planning, memory, ...
├── analects/                # Expert configurations (code, infrastructure, ...)
├── server/                  # HTTP server (FastAPI)
│   ├── app.py               # Routes, session handling, expert routing
│   ├── expert_router.py     # Request classifier
│   ├── tool_groups.py       # Route → tool set mapping
│   ├── code_intelligence/   # Workspace indexing, code search
│   └── user/                # User identification, profiles, memory
└── lib/                     # Runtime bootstrap
```

## Origin

CCA is a fork of [Meta + Harvard's Confucius framework](https://github.com/facebookresearch/cca-swebench) ([paper](https://arxiv.org/abs/2512.10398)), originally designed as a SWE-bench agent harness. This fork extends it into a standalone Agent-as-a-Model server with expert routing, user awareness, code intelligence, and local inference optimization.

## License

MIT — see [LICENSE](LICENSE).
