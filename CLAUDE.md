# Confucius Code Agent (CCA) - Development Guide

**Base Directory**: `nvidia-dgx-spark/cca/`
**Fork**: https://github.com/seli-equinix/cca-swebench
**Upstream**: https://github.com/facebookresearch/cca-swebench
**Origin**: Meta + Harvard research project (arXiv:2512.10398)

---

## CRITICAL: Two-Repo Git Workflow

CCA is a **git submodule** of `docker-swarm-stacks`. It has its own repo.

```
docker-swarm-stacks/          <- parent repo (seli-equinix/docker-swarm-stacks)
  nvidia-dgx-spark/
    cca/                      <- submodule (seli-equinix/cca-swebench)
      confucius/              <- the agent framework
```

### Committing CCA Changes

CCA changes require **two commits** - one in the submodule, one in the parent:

```bash
# 1. Commit inside the submodule
cd nvidia-dgx-spark/cca
git add <files> && git commit -m "description" && git push origin main

# 2. Update the parent repo's submodule pointer
cd /home/seli/docker-swarm-stacks
git add nvidia-dgx-spark/cca && git commit -m "update CCA submodule" && git push
```

### Pulling Upstream Updates

```bash
cd nvidia-dgx-spark/cca
git fetch upstream
git merge upstream/main
git push origin main
```

### Cloning Fresh (on Spark1 or new machine)

```bash
cd docker-swarm-stacks
git submodule update --init --recursive nvidia-dgx-spark/cca
```

---

## Architecture Overview

CCA is a modular LLM agent framework built on LangChain with an extension-based tool system.

```
CLI (confucius code)
  -> Confucius (session manager)
    -> CodeAssistEntry (Analect)
      -> AnthropicLLMOrchestrator (agent loop)
        -> Extensions (tools: file edit, bash, planning, memory)
        -> AutoLLMManager -> LLM Provider (OpenAI/Azure/Bedrock/Google)
```

### Core Components

| Directory | Purpose | Key Classes |
|-----------|---------|-------------|
| `confucius/cli/` | CLI entry point | `main.py` (Click app, `confucius code`) |
| `confucius/lib/` | Runtime bootstrap | `Confucius`, `run_entry_repl` |
| `confucius/analects/code/` | Code agent config | `CodeAssistEntry`, LLM params, allowed commands |
| `confucius/analects/note_taker/` | Note-taking agent | Observes traces, persists long-term memory |
| `confucius/core/` | Foundation layer | `Analect`, `AutoLLMManager`, memory, storage |
| `confucius/orchestrator/` | Agent execution loop | `AnthropicLLMOrchestrator`, Extension pipeline |
| `confucius/orchestrator/extensions/` | Tool implementations | File edit, bash, planning, memory, caching |
| `confucius/utils/` | Helpers | JSON, async, string, pydantic utilities |
| `scripts/` | SWE-bench harness | `run_swebench.py`, `run_sbp.sh` |

---

## LLM Provider Routing

`AutoLLMManager` routes by model name prefix:

| Model Pattern | Provider | Backend | Env Vars |
|---------------|----------|---------|----------|
| Contains `claude` | `BedrockLLMManager` | AWS Bedrock | `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Contains `gemini` | `GoogleLLMManager` | Google AI | Google credentials |
| Matches `gpt`, `o1`, `o3`, `o4` | `AzureLLMManager` | Azure OpenAI | Azure config |
| Matches `OPENAI_MODEL_PREFIXES` | `OpenAILLMManager` | OpenAI API | `OPENAI_API_KEY`, `OPENAI_BASE_URL` |

**IMPORTANT**: `OPENAI_MODEL_PREFIXES` is currently **empty** (`[]`), so no models route to the OpenAI provider by default. The `gpt-*` prefix routes to **Azure**, not OpenAI.

### Default Model

The code agent defaults to `GPT5_2_THINKING` (`model="gpt-5.2"`) which routes to **Azure**.

Pre-defined LLM params in `analects/code/llm_params.py`:
- `GPT5_2_THINKING` - GPT-5.2 with 32K thinking budget (default)
- `GPT5_1_THINKING` - GPT-5.1 with 32K thinking budget
- `CLAUDE_4_5_SONNET_THINKING` - Claude 4.5 Sonnet with 8K thinking
- `CLAUDE_4_5_OPUS` - Claude Opus 4.5

### Using Local vLLM (Spark2)

To use our local vLLM (Qwen3-Next-80B-A3B-FP8 on Spark2:8000), you need to:

1. **Add model prefix to OpenAI routing** in `core/llm_manager/constants.py`:
   ```python
   OPENAI_MODEL_PREFIXES = ["qwen", "/models/"]
   ```

2. **Create LLM params** in `analects/code/llm_params.py`:
   ```python
   QWEN3_LOCAL = LLMParams(
       model="/models/Qwen3-Next-80B-A3B-Thinking-FP8",
       initial_max_tokens=4096,
       temperature=0.3,
   )
   ```

3. **Wire it in** `analects/code/entry.py`:
   ```python
   from .llm_params import QWEN3_LOCAL
   # ...
   orchestrator = AnthropicLLMOrchestrator(
       llm_params=[QWEN3_LOCAL],
       ...
   )
   ```

4. **Set env vars**:
   ```bash
   OPENAI_API_KEY=dummy
   OPENAI_BASE_URL=http://192.168.4.208:8000/v1
   ```

**Caveat**: The `AnthropicLLMOrchestrator` uses Anthropic-style tool_use format. vLLM with Qwen may need `use_responses_api=False` in the OpenAI adapter (falls back to `chat.completions` instead of the OpenAI Responses API) and the model must support tool calling. The `OpenAILLMManager._get_chat()` defaults to `use_responses_api=True` -- this will likely need changing for vLLM compatibility.

---

## Extensions (Agent Tools)

The orchestrator runs an extension pipeline. Each extension registers tag handlers and tool schemas.

| Extension | File | Capabilities |
|-----------|------|-------------|
| `LLMCodingArchitectExtension` | `extensions/plan/llm.py` | Planning phase before execution |
| `FileEditExtension` | `extensions/file/edit.py` | View, create, edit files (line-range diffs) |
| `CommandLineExtension` | `extensions/command_line/base.py` | Bash execution (allowlisted commands) |
| `FunctionExtension` | `extensions/function/` | Python function calling (placeholder) |
| `PlainTextExtension` | `extensions/plain_text.py` | Raw text pass-through |
| `HierarchicalMemoryExtension` | `extensions/memory/hierarchical.py` | Long-term memory with summarization |
| `AnthropicPromptCaching` | `extensions/caching/anthropic.py` | Anthropic token cache reuse |
| `SoloModeExtension` | `extensions/solo.py` | Single-shot execution mode |

### Allowed CLI Commands

Defined in `analects/code/commands.py`. Conservative allowlist:
- Filesystem: `pwd`, `ls`, `cat`, `head`, `tail`, `find`, `cp`, `mv`, `rm`, `mkdir`, `touch`, `chmod`
- Text: `grep`, `sed`, `awk`, `cut`, `sort`, `uniq`, `tr`, `xargs`
- Archive: `tar`, `gzip`
- Network: `curl`, `wget`
- Git: `git` (all subcommands)
- Python: `python3`

---

## Orchestrator Loop

```
while iterations < max_iterations:
  1. on_input_messages()     -> preprocess (extensions inject context)
  2. get_llm_params()        -> select model/temperature for this turn
  3. invoke_llm()            -> call LLM via AutoLLMManager
  4. parse response          -> extract XML tags, plain text, tool_use blocks
  5. on_plain_text()         -> extension handlers for text output
  6. on_tag()                -> match tag to extension, execute tool
  7. on_process_messages_complete() -> post-processing
```

Exceptions: `OrchestratorInterruption` (pause), `OrchestratorTermination` (stop), `MaxIterationsReachedError`.

---

## Session & Storage

| Item | Location |
|------|----------|
| Session data | `~/.confucius/sessions/{session_id}/` |
| Memory | `~/.confucius/sessions/{session_id}/memory/` |
| Storage | `~/.confucius/sessions/{session_id}/storage/` |
| Artifacts | `~/.confucius/sessions/{session_id}/artifacts/` |
| Trajectory dumps | `/tmp/confucius/traj_{session_id}.json` |

Session IDs are UUID-based, auto-generated per run.

---

## Build & Deploy (Spark1)

### Docker Commands

```bash
# Build image
cd nvidia-dgx-spark/cca
docker compose -f cca-compose.yml build

# Run interactive REPL
docker compose -f cca-compose.yml run --rm cca

# Run with source mounted (no rebuild for code changes)
docker compose -f cca-compose.yml --profile dev run --rm cca-dev

# Open shell for debugging
docker compose -f cca-compose.yml run --rm cca bash
```

### Deploy Script (from node5)

```bash
./nvidia-dgx-spark/cca/deploy-cca.sh build   # pull + build on Spark1
./nvidia-dgx-spark/cca/deploy-cca.sh run     # interactive REPL on Spark1
./nvidia-dgx-spark/cca/deploy-cca.sh dev     # source-mounted dev mode
./nvidia-dgx-spark/cca/deploy-cca.sh shell   # bash inside container
```

### Docker Services

| Service | Purpose | Profile |
|---------|---------|---------|
| `cca` | Interactive REPL (production) | default |
| `cca-dev` | Source-mounted for live editing | `dev` |
| `cca-swebench` | SWE-bench runner | `swebench` |

---

## Environment Variables

### Required

```env
OPENAI_API_KEY=dummy                              # or real key for OpenAI/Azure
OPENAI_BASE_URL=http://192.168.4.208:8000/v1     # local vLLM on Spark2
```

### Optional (provider-specific)

```env
# AWS Bedrock (for Claude models)
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_BEARER_TOKEN_BEDROCK=...

# Workspace
CCA_WORKSPACE=/home/seli/code
```

---

## Key Files to Modify

When adapting CCA for local infrastructure:

| File | What to Change |
|------|---------------|
| `confucius/core/llm_manager/constants.py` | Add model prefixes to `OPENAI_MODEL_PREFIXES` for vLLM routing |
| `confucius/core/llm_manager/openai.py` | Change `use_responses_api=False` for vLLM compat |
| `confucius/analects/code/llm_params.py` | Add `QWEN3_LOCAL` params for our model |
| `confucius/analects/code/entry.py` | Switch default `llm_params` to local model |
| `confucius/analects/code/commands.py` | Add/remove allowed CLI commands |
| `confucius/analects/code/tasks.py` | Modify system prompt / task definition |

---

## Testing

No formal test suite in the upstream repo. SWE-bench is the primary validation:

```bash
# Build PEX binary for container deployment
pex . -r requirements.txt -m scripts.run_swebench -o app.pex

# Run SWE-bench instance
docker compose -f cca-compose.yml --profile swebench run --rm cca-swebench
```

---

## Upstream Sync

```bash
cd nvidia-dgx-spark/cca
git fetch upstream
git log --oneline upstream/main..HEAD   # see what we've added
git merge upstream/main                 # pull in upstream changes
git push origin main                    # push merged result to fork
```
