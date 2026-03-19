# Analects

**Agent-as-a-Model for code** — built on [Meta/Harvard's Confucius framework](https://arxiv.org/abs/2512.10398).

An AI coding agent that runs as an **Agent-as-a-Model** HTTP server. Send it OpenAI-compatible `/v1/chat/completions` requests, and it runs a full agent loop internally — reading files, executing commands, editing code, searching the web, and managing long-term memory — then returns the result as a standard chat completion.

> **Reference deployment**: This project runs on two [NVIDIA DGX Spark](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) units (Grace Blackwell GB10 SoC, 128GB unified memory each). It can be adapted to any vLLM-compatible setup — see [Adapting to Your Hardware](#adapting-to-your-hardware).

```
┌─────────────────────────────────────────────────────────────────────┐
│  Client (any OpenAI-compatible tool)                                │
│  Continue.dev, Cursor, curl, Python SDK, ...                        │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ POST /v1/chat/completions
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Analects Server (:8500)                            [Spark1]        │
│                                                                     │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐   │
│  │ Expert       │───>│ Agent Loop (DualModelOrchestrator)       │   │
│  │ Router       │    │                                          │   │
│  │ Functionary  │    │  Plan → Execute → Observe → Repeat       │   │
│  │ 8B (llama    │    │                                          │   │
│  │ .cpp :8001)  │    │  Tools: bash, file edit, web search,     │   │
│  └─────────────┘    │  code review, test gen, memory, ...      │   │
│                      └──────────────┬───────────────────────────┘   │
│                                     │                               │
│  ┌──────────────────────────────────▼──────────────────────────┐   │
│  │ Redis :6379 │ Qdrant :6333 │ Embedding :8200 │ SearXNG :8888│  │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────┬───────────────────────────────┘
                                      │ LLM inference
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│  vLLM Server (:8000)                             [Spark2]           │
│  Qwen3.5-35B-A3B-FP8 (coder, planner, search, reviewer, tester)   │
└─────────────────────────────────────────────────────────────────────┘
```

## Why Agent-as-a-Model?

Most AI coding tools require specific IDE plugins or CLI clients. Analects takes a different approach: it exposes the full agent as a standard OpenAI-compatible model endpoint.

This means **any tool that can talk to the OpenAI API can use Analects** — Continue.dev, Cursor, custom scripts, or a simple `curl`. The agent loop (planning, tool use, iteration) happens server-side. The client just sees a chat completion response.

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
- **Workspace sync** — auto-clones and syncs repos from GitLab with hot-reload config (no restart needed)
- **Long-term memory** — note-taker observes every session and persists insights to vector DB
- **Web search** — SearXNG integration for real-time information
- **Phoenix tracing** — full OpenTelemetry observability for every agent run
- **TOML config** — switch between local vLLM and cloud providers (Azure, Bedrock, Google) with a config change
- **Self-contained stack** — single `./setup.sh setup` + `docker compose up -d` runs all 11 containers
- **Production-grade routing** — smart message truncation, data block stripping, configurable timeouts

---

## Quick Start

### 1. Clone and setup

```bash
git clone https://github.com/seli-equinix/analects.git
cd analects

# First time: checks prereqs, creates config files, pulls Docker images
./setup.sh setup

# Edit configs with your values
nano .env             # Set REDIS_PASSWORD, MODELS_DIR, VLLM_URL
nano config.toml      # Set main vLLM URL in [providers.local.coder] base_url
```

### 2. Configure your LLM backend

Edit `config.toml` to point at your inference servers:

```toml
# Top-level: route Qwen model names to OpenAI-compatible manager
openai_model_prefixes = ["qwen", "/models/"]

[active]
coder = "local"             # Use local vLLM for code generation
note_taker = "local"        # Use local small model for note-taking
tool_orchestrator = "local" # 8B model for research tool iterations
planner = "local"
reviewer = "local"
tester = "local"
search = "local"
search_researcher = "local" # Researcher for search tool iterations

[providers.local.coder]
model = "/models/Qwen3.5-35B-A3B-FP8"
provider = "openai"
base_url = "http://your-vllm-host:8000/v1"
api_key_env = "OPENAI_API_KEY"
initial_max_tokens = 8192           # first response token limit
max_tokens = 16384                  # subsequent iterations
temperature = 0.3
# thinking_budget = 32768           # for models with extended thinking
# cost_per_1m_input = 0.0           # for usage tracking (local = free)
# cost_per_1m_output = 0.0

[providers.local.note_taker]
model = "/models/Qwen3-8B-FP8"
provider = "openai"
base_url = "http://your-notetaker-host:8400/v1"
api_key_env = "OPENAI_API_KEY"
initial_max_tokens = 4096
max_tokens = 8192
temperature = 0.3
```

Configure backend services:

```toml
[services]
redis_url = "redis://:yourpassword@your-redis-host:6379/0"
qdrant_url = "http://your-qdrant-host:6333"
embedding_url = "http://your-embedding-host:8200"
searxng_url = "http://your-searxng-host:8888"        # optional
memgraph_host = "your-memgraph-host"                  # optional
memgraph_port = 7687

[router]
enabled = true
url = "http://your-functionary-host:8001"
timeout_ms = 10000
fallback_entry = "coder"
temperature = 0.1

# In-loop tool selection (smart tool escalation during agent execution)
[tool_router]
enabled = true
url = "http://your-functionary-host:8001"
timeout_ms = 10000
temperature = 0.1
```

Or use cloud providers instead of local vLLM:

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

### 3. Start the full stack

```bash
# Start all 11 containers
docker compose up -d

# Check service health
./setup.sh status
```

This starts Redis, Qdrant, Memgraph, SearXNG, Embedding server, Note-taker, Functionary router, Analects, and workspace-sync — all configured via `.env` and `config.toml`.

> **Note**: The main vLLM inference server (coder model on port 8000) runs on a separate machine. Set `VLLM_URL` in `.env` to point to it.

### 4. Test it

```bash
# Health check
curl http://localhost:8500/health

# List models
curl http://localhost:8500/v1/models

# Send a coding task
curl -X POST http://localhost:8500/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"analects","messages":[{"role":"user","content":"List all Python files in /workspace and summarize what they do"}]}'

# Stream a response
curl -X POST http://localhost:8500/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"analects","messages":[{"role":"user","content":"Hello, what can you help me with?"}],"stream":true}'
```

Manage the stack: `./setup.sh stop`, `./setup.sh logs [service]`, `./setup.sh status`

---

## Infrastructure Requirements

Analects is not just one container — it's a stack of services that work together.

### Required Models

| Model | Purpose | Size | Where It Runs |
|-------|---------|------|---------------|
| **Qwen3.5-35B-A3B-FP8** | Coder, planner, reviewer, tester, search | ~20GB | vLLM on Spark2 (:8000) |
| **Qwen3-8B-FP8** (or Qwen3.5-9B) | Note-taker, tool orchestrator | ~9GB | vLLM on Spark1 (:8400) |
| **Qwen3-Embedding-8B** | Semantic search embeddings (4096 dims) | ~8GB | Embedding server on Spark1 (:8200) |
| **functionary-small-v3.2.Q4_0.gguf** | Expert router (request classification) | ~4GB | llama.cpp on Spark1 (:8001) |

> **Note**: Any OpenAI-compatible models work. The Qwen models listed above are what the reference deployment uses. You can substitute with any model that supports tool calling.

### Required Services

These must be running before Analects starts:

| Service | Port | Container/Image | Purpose |
|---------|------|-----------------|---------|
| **vLLM (coder)** | 8000 | vLLM with your large model | Primary LLM for all agent work |
| **vLLM (note-taker)** | 8400 | vLLM with a small model | Background note extraction + tool orchestration |
| **Functionary Router** | 8001 | llama.cpp `server` | Request classification before agent loop |
| **Redis** | 6379 | `redis:7-alpine` | Session state, critical facts, trajectories |
| **Qdrant** | 6333 | `qdrant/qdrant:v1.14` | Vector DB for user profiles, code search, notes |
| **Embedding Server** | 8200 | vLLM or TEI with embedding model | Generates 4096-dim vectors for semantic search |

### Optional Services

Analects degrades gracefully without these:

| Service | Port | Purpose | What Happens Without It |
|---------|------|---------|------------------------|
| **SearXNG** | 8888 | Web search | `web_search` tool unavailable |
| **Memgraph** | 7687 | Code knowledge graph | Falls back to basic code search |
| **Phoenix** | 4317 | OpenTelemetry trace collection | No tracing (set `phoenix_endpoint = ""`) |

### Reference Deployment: Two DGX Sparks

```
┌─────────────────────────────────────────────────────────────────┐
│  Spark1 (128GB unified memory)                                  │
│                                                                 │
│  Analects Server ────────────── :8500  (agent HTTP endpoint)    │
│  Workspace Sync ─────────────── auto   (GitLab repo sync)      │
│  Functionary Router ──────── :8001  (llama.cpp, ~4GB)           │
│  vLLM Note-Taker ────────── :8400  (Qwen3-8B, ~9GB)            │
│  Embedding Server ────────── :8200  (Qwen3-Embedding-8B, ~8GB) │
│  Redis ───────────────────── :6379  (sessions, facts)           │
│  Qdrant ──────────────────── :6333  (vector DB)                 │
│  SearXNG ─────────────────── :8888  (web search)                │
│  Memgraph ────────────────── :7687  (knowledge graph)           │
│                                                                 │
│  GPU memory: ~21GB models + ~25GB KV caches                     │
│  Remaining: ~82GB available for OS/containers                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  Spark2 (128GB unified memory)                                  │
│                                                                 │
│  vLLM (coder) ────────────── :8000  (Qwen3.5-35B-A3B-FP8)     │
│                                                                 │
│  GPU memory: ~20GB model + ~90GB KV cache                       │
│  Dedicated to inference — nothing else runs here                │
└─────────────────────────────────────────────────────────────────┘
```

### Adapting to Your Hardware

Analects doesn't require DGX Spark hardware. Any setup that can serve OpenAI-compatible endpoints works:

- **Single powerful GPU** (80GB+ VRAM): Run all models on one machine, adjust ports in `config.toml`
- **Cloud inference**: Set `[active] coder = "cloud"` and configure Azure/Bedrock/Google providers
- **Mixed**: Local small model for note-taker, cloud API for coder
- **CPU-only router**: Functionary runs fine on CPU via llama.cpp (slower but works)

The only hard requirements are Redis and Qdrant — everything else is configurable via `config.toml`.

---

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

Analects uses two models working together:

- **Coder** (large model, e.g. 35B) — handles the actual agent work: planning, tool calling, code generation
- **Note-taker** (small model, e.g. 8B) — observes every session in the background, extracts insights, and stores them in Qdrant for future context enrichment

This means Analects learns from past sessions and gets better at helping you over time, without paying large-model costs for memory extraction.

### How a Request Flows

```
1. Client sends POST /v1/chat/completions
2. Expert Router (Functionary 8B) classifies: "coder", "infrastructure", "search", etc.
3. If "direct" or "clarify" → return immediately (no agent loop)
4. Otherwise → build tool set for that expert type
5. Inject user context from past sessions (Qdrant lookup)
6. Enter agent loop:
   a. Planner generates a plan
   b. Coder executes tools (bash, file edit, search, ...)
   c. Observe results, iterate until done
7. Return response (streaming SSE or single JSON)
8. Background: Note-taker extracts insights → Qdrant
```

### Workspace Sync & GitLab Integration

The `workspace-sync` container keeps the agent's code context up to date by cloning and syncing repositories from any git server (GitLab, GitHub, etc.) into `/workspace/`. The agent can then search, read, and work on your code.

**Key features:**
- **Hot-reload config** — add or remove repos in `config.toml` without restarting any container
- **Configurable sync interval** (default: 60s)
- **Automatic reindexing** — triggers Qdrant + Memgraph indexer after each sync
- **Stale data cleanup** — removes repos from `/workspace/` and indexes when removed from config
- **Two repo types**: `source` (read-only, periodic pull) and `migration` (Analects can push commits)

#### Step 1: Set credentials in `.env`

```env
# GitLab (or any git server)
GITLAB_PASS=your-gitlab-password

# GitHub (optional — for syncing GitHub repos)
# GITHUB_TOKEN=ghp_your_token_here
```

#### Step 2: Configure repos in `config.toml`

```toml
[workspace]
sync_interval = 60                      # seconds between git pulls

# Credentials — ${VAR} references are resolved from .env at runtime
[[workspace.credentials]]
id = "gitlab-local"
url = "http://your-gitlab-host:8929"    # your GitLab instance
user = "root"
token = "${GITLAB_PASS}"                # references GITLAB_PASS from .env

# Optional: add more git servers
# [[workspace.credentials]]
# id = "github"
# url = "https://github.com"
# user = "your-username"
# token = "${GITHUB_TOKEN}"

# Repositories to sync
[[workspace.repos]]
name = "my-project"                     # folder name in /workspace/
repo = "root/my-project"               # <user>/<repo> path on the git server
credential = "gitlab-local"             # references the credential block above
type = "source"                         # "source" = read-only, "migration" = push access
branch = "main"

[[workspace.repos]]
name = "my-project-migration"
repo = "root/my-project-migration"
credential = "gitlab-local"
type = "migration"                      # Analects can commit and push to this repo
branch = "main"
```

#### Step 3: Code Intelligence (automatic)

Once repos are synced, the indexer automatically:
1. Indexes all files into **Qdrant** (`codebase_files` collection) for semantic code search
2. Builds a **Memgraph** knowledge graph of code relationships
3. Makes code searchable via the agent's `code_search` and `file_search` tools

Configure indexer behavior in `config.toml`:

```toml
[indexer]
paths = ["/workspace"]
sync_interval = 300                     # seconds between re-index cycles
collection = "codebase_files"
skip_dirs = [".git", "node_modules", "__pycache__", ".venv"]
```

#### How it works end-to-end

```
1. You push code to GitLab/GitHub
2. workspace-sync pulls changes every 60s → /workspace/my-project/
3. Indexer re-indexes changed files → Qdrant vectors + Memgraph graph
4. User asks Analects: "How does the auth module work?"
5. Agent searches indexed code, reads files, and answers with full context
6. For migration repos: agent can edit files and push commits back
```

---

## Configuration

All configuration lives in three files (none tracked by git — copy from `*.example`):

| File | Purpose |
|------|---------|
| `config.toml` | Models, providers, service URLs, router settings, workspace repos, indexer |
| `infrastructure.toml` | Cluster topology for infra expert (SSH hosts, services) |
| `.env` | Secrets: Redis password, API keys, GitLab/GitHub tokens |

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

# Git server credentials (for workspace-sync)
GITLAB_PASS=your-gitlab-password
# GITHUB_TOKEN=ghp_your_token_here
```

---

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
| `POST` | `/workspace/reindex` | Trigger workspace reindexing |

---

## Development

### Local Development (source-mounted)

```bash
# Start with source code mounted (no rebuild for code changes)
docker compose --profile dev up -d cca-dev
```

### Without Docker

```bash
conda create -n analects python=3.12 -y
conda activate analects
pip install -r requirements.txt

# Run the server
python -m confucius --port 8500
```

### Project Structure

```
analects/
├── setup.sh                 # Stack manager (setup, start, stop, status, logs)
├── docker-compose.yml       # All 11 services in one file
├── config.toml.example      # LLM providers, services, workspace repos
├── .env.example             # Secrets template
├── confucius/
│   ├── __main__.py          # Entry point (confucius --port 8500)
│   ├── core/                # Config (hot-reload), LLM managers, tracing, memory
│   │   └── config.py        # TOML config loader (pydantic-validated, hot-reload)
│   ├── orchestrator/        # Agent loop, extension pipeline
│   │   └── extensions/      # Tools: file edit, bash, planning, memory, ...
│   ├── analects/            # Expert configurations
│   │   ├── code/            # Coder: system prompt, allowed commands
│   │   └── infrastructure/  # Infra: SSH access, cluster topology
│   └── server/              # HTTP server (FastAPI)
│       ├── app.py           # Routes, session handling, expert routing
│       ├── expert_router.py # Functionary-based classifier (smart truncation)
│       ├── tool_groups.py   # Route → tool set mapping
│       ├── note_observer.py # Background note extraction (per-request)
│       ├── dual_model_orchestrator.py  # Two-LLM coordination
│       ├── code_intelligence/  # Workspace indexing, code search, knowledge graph
│       │   ├── workspace_indexer.py  # Config-driven project indexing
│       │   └── trace_extension.py    # Code tracing and assembly
│       └── user/            # User identification, profiles, memory
├── workspace-sync/          # GitLab repo sync with hot-reload
│   └── sync.py              # Structured logging, auto-detect, stale cleanup
├── stack/                   # Self-contained infrastructure
│   ├── embedding-server/    # Qwen3-Embedding-8B Dockerfile
│   ├── functionary-router/  # llama.cpp router Dockerfile
│   ├── vllm-notetaker/      # Note-taker vLLM Dockerfile
│   ├── redis/               # Redis stack config
│   ├── qdrant/              # Qdrant stack config
│   ├── searxng/             # SearXNG + Valkey config
│   └── memgraph/            # Knowledge graph config
└── tests/
    └── integration/         # Real infrastructure tests
        ├── test_eva_full_trace.py      # End-to-end code tracing
        └── test_tool_calling_e2e.py    # Tool execution verification
```

---

## Recent Changes

### Self-Contained Stack (March 2026)
- All 11 services defined in a single `docker-compose.yml` with Docker Hub images
- `./setup.sh setup` handles first-time prereq checks, config creation, and image pulls
- No external dependencies beyond Docker and a GPU

### Workspace Sync & Hot-Reload Config
- `workspace-sync` container clones/pulls from GitLab into `/workspace/`
- Config changes (adding/removing repos) apply without restarting any container
- Structured JSON logging with error escalation

### Production-Grade Router
- Smart message truncation for the Functionary classifier (prevents overflows)
- Data block stripping (base64, large JSON) before classification
- Configurable timeouts per route

### Code Intelligence
- Config-driven `project_map` replaces hardcoded `workspace_root`
- Code tracing: trace execution paths and assemble into files
- Tree-sitter PowerShell parser (pre-compiled v0.26.3, ABI v14)

### Project Rename
- Renamed from `confucius-code-agent` to **Analects**
- Detached from upstream fork (`facebookresearch/cca-swebench`) — fully independent repo
- Published to Docker Hub under `hellohal2064/` namespace

---

## Origin

Analects is built on [Meta + Harvard's Confucius framework](https://github.com/facebookresearch/cca-swebench) ([paper](https://arxiv.org/abs/2512.10398)), originally designed as a SWE-bench agent harness. This project extends it into a standalone Agent-as-a-Model server with expert routing, user awareness, code intelligence, workspace sync, and local inference optimization.

## License

MIT — see [LICENSE](LICENSE).
