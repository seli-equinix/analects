# MCP Server Tools — Complete Migration Guide to CCA

**Date**: 2026-02-22
**Purpose**: Comprehensive reference for migrating every MCP server tool into CCA's native extension system
**Source**: `nvidia-dgx-spark/mcp-server/mcp_server.py` (10,650 lines), `mcp_tools.py` (1,159 lines)

---

## Overview

| Metric | Value |
|--------|-------|
| Total tools | 38 (33 LLM-callable + 5 MCP-protocol-only) |
| Tool definitions | `mcp_server.py` lines 351–1213 (`AVAILABLE_TOOLS` list) |
| Tool dispatch | `mcp_server.py` lines 1415–3100 (`execute_tool()` function) |
| MCP-only tools | `mcp_tools.py` lines 121–1046 (`MCPToolsManager` class) |
| Recovery hints | `mcp_server.py` lines 1227–1254 (`TOOL_RECOVERY_SUGGESTIONS`) |

### CCA Migration Target

Each MCP tool becomes a method inside a CCA `ToolUseExtension` subclass. Pattern:

```python
class MyToolsExtension(ToolUseExtension):
    @property
    async def tools(self) -> list[ant.ToolLike]:
        return [ant.Tool(name="tool_name", description="...", input_schema={...})]

    async def _on_tool_use(self, tool_use, context) -> ant.MessageContentToolResult:
        if tool_use.name == "tool_name":
            result = await self._handle_tool_name(tool_use.input)
            return ant.MessageContentToolResult(tool_use_id=tool_use.id, content=json.dumps(result))
```

Reference implementation: [tools_extension.py](../confucius/server/user/tools_extension.py) (5 user tools already ported)

---

## Category 1: Memory & Search Tools (5 tools)

### 1.1 `search_memory`

**What it does**: Searches Redis conversation history + Qdrant long-term memory

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query |
| `collection` | enum | No | `"any"` | `"conversations"`, `"code_snippets"`, `"solved_problems"`, `"any"` |
| `n_results` | integer | No | 3 | 1–10 results |

**Implementation** (`mcp_server.py:1505–1548`):
```python
if collection in ("conversations", "any"):
    results = await memory.search_long_term(query, n_results=n_results)
if collection in ("code_snippets", "any"):
    results += await memory.search_code_snippets(query, n_results=n_results)
# Content truncated at ~2000 chars per result
```

**Backend**: Redis (conversation cache) + Qdrant (long-term semantic search)
**Migration notes**: CCA has `HierarchicalMemoryExtension` with file-based memory. Consider wrapping Qdrant search as a new tool or extending the existing memory extension.

---

### 1.2 `web_search`

**What it does**: Internet search via SearXNG

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query |
| `n_results` | integer | No | 5 | 1–10 results |
| `categories` | string | No | — | `"general"`, `"it"`, `"science"`, `"files"`, `"social media"` |

**Implementation** (`mcp_server.py:1550–1613`):
```python
params = {"q": query, "format": "json", "language": "en"}
if categories:
    params["categories"] = categories
resp = await client.get(f"{SEARXNG_URL}/search", params=params, timeout=15.0)
# Auto-retry: if 0 results, simplify query (strip stopwords, keep max 5 words)
# Extracts: title, url, content (first 500 chars) per result
```

**Backend**: SearXNG at `192.168.4.205:8888`
**Migration notes**: Pure HTTP call — no state, no dependencies on other MCP modules. Easy standalone port.

---

### 1.3 `search_knowledge`

**What it does**: Unified semantic search across ephemeral docs, user knowledge, and project knowledge

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query |
| `n_results` | integer | No | 10 | 1–20 results |
| `project` | string | No | — | Filter by project name |
| `language` | enum | No | — | `"powershell"`, `"bash"`, `"python"`, `"yaml"`, `"json"`, `"markdown"`, `"any"` |
| `tiers` | array[string] | No | — | `["ephemeral", "user", "project"]` |

**Implementation** (`mcp_server.py:1430–1503`):
```python
results = await knowledge_search.smart_search(
    query=query, n_results=n_results, project=project, language=language,
    session_id=session_id,  # if "ephemeral" in tiers
    user_id=user_id,        # if "user" in tiers
)
# Includes graph_context (callers/callees) when Memgraph available
# ~3000 chars per result, distributed intelligently
```

**Backend**: Qdrant (multiple collections: ephemeral_docs, user_*_knowledge, codebase_files) + Memgraph enrichment
**Dependencies**: `knowledge_search.py`, `qdrant_adapter.py`, `memgraph_adapter.py`
**Migration notes**: Most complex search tool. Requires Qdrant client + embedding server. Consider splitting into separate tools (search_user_knowledge, search_project_knowledge) for CCA.

---

### 1.4 `search_codebase`

**What it does**: Search indexed source code from Nextcloud WebDAV

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query |
| `language` | enum | No | — | `"powershell"`, `"bash"`, `"python"`, etc. |
| `project` | string | No | — | Filter by project |
| `n_results` | integer | No | 5 | 1–20 results |

**Implementation**: Routes through `search_knowledge` with `tiers=["project"]`
**Backend**: Qdrant codebase_files collection
**Migration notes**: Could be merged with search_knowledge or kept as convenience alias.

---

### 1.5 `fetch_url_content`

**What it does**: Fetch URL content with HTML text extraction and SSRF protection

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | — | URL to fetch |
| `extract_text` | boolean | No | true | Extract readable text from HTML |
| `timeout` | integer | No | 30 | Max seconds (cap 60) |

**Implementation** (`mcp_server.py:2608–2689`):
```python
# Security: resolve hostname, block private/loopback/link-local IPs
parsed = urlparse(url)
ip = socket.getaddrinfo(parsed.hostname, None)[0][4][0]
if ipaddress.ip_address(ip).is_private:
    raise SecurityError("Cannot fetch private IP addresses")

resp = await client.get(url, follow_redirects=True, timeout=timeout)

# If HTML + extract_text: BeautifulSoup text extraction
# Remove: script, style, nav, footer, header, aside tags
# Content truncated at 50KB
```

**Backend**: httpx.AsyncClient (shared connection pool)
**Security**: SSRF protection (IP filtering), 50KB content cap
**Migration notes**: Standalone HTTP utility. Need `httpx` + `beautifulsoup4`.

---

## Category 2: User Management Tools (6 tools)

### 2.1 `identify_user`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | — | User's name |

**Implementation** (`mcp_server.py:1749–1858`):
```python
user = await session_manager.find_user_by_name(name)  # fuzzy embedding search
if user:
    await link_session_to_user(session, user, client_type)
    # Add name as alias if different from display_name
else:
    profile = UserProfile(user_id=uuid4(), display_name=name, ...)
    # Apply pending_facts/preferences BEFORE save
    await save_user_profile(profile)
    await link_session_to_user(session, profile)
```

**Backend**: Qdrant user_profiles collection + Redis sessions
**Status**: **ALREADY PORTED** to CCA in `tools_extension.py`

---

### 2.2 `infer_user`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `message` | string | Yes | — | First user message to analyze for identity clues |

**Implementation** (`mcp_server.py:1860–1929`):
```python
result = await session_manager.infer_user_from_message(message, session)
# Returns: matched (bool), confidence (0-1.0)
# recommendation: "auto_link" (>0.80), "ask" (0.60-0.80), "anonymous" (<0.60)
# potential_user: {display_name, user_id, facts_preview, total_sessions}
# all_matches: list for ambiguous cases
```

**Backend**: Embedding server (Spark1:8200) → Qdrant similarity search
**Status**: **ALREADY PORTED** to CCA in `tools_extension.py`

---

### 2.3 `remember_user_fact`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `fact` | string | Yes | — | The fact to remember |
| `key` | string | No | MD5(fact)[:8] | Fact category/key |
| `value` | string | No | `fact` | Fact value |

**Implementation** (`mcp_server.py:1662–1710`):
```python
if not key:
    key = hashlib.md5(fact.encode()).hexdigest()[:8]
if not value:
    value = fact

if session.identified:
    await session_manager.update_user_facts(user_id, {key: value})
else:
    session.context.setdefault("pending_facts", {})[key] = value  # saved when identified later
```

**Backend**: Qdrant user_profiles (if identified) or session context (if anonymous)
**Status**: **ALREADY PORTED** to CCA in `tools_extension.py`

---

### 2.4 `update_user_preference`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `preference` | string | Yes | — | Preference key |
| `value` | string | Yes | — | Preference value |

**Implementation** (`mcp_server.py:1712–1747`):
```python
if session.identified:
    await session_manager.update_user_preferences(user_id, {preference: value})
else:
    session.context.setdefault("pending_preferences", {})[preference] = value
```

**Backend**: Qdrant user_profiles
**Status**: **ALREADY PORTED** to CCA in `tools_extension.py`

---

### 2.5 `get_user_context`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| (none) | — | — | — | — |

**Implementation** (`mcp_server.py:1636–1660`):
```python
context = await session_manager.build_user_context(session)
# Returns: is_identified, display_name, facts, preferences, skills
```

**Status**: **ALREADY PORTED** to CCA in `tools_extension.py`

---

### 2.6 `manage_user_profile`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `action` | enum | Yes | — | `"get"`, `"update_facts"`, `"update_preferences"`, `"add_skill"`, `"remove_skill"` |
| `facts` | object | No | — | For update_facts |
| `preferences` | object | No | — | For update_preferences |
| `skill` | string | No | — | For add/remove_skill |

**Implementation** (`mcp_server.py` — dispatches to session_manager methods):
- `get`: Returns full user profile
- `update_facts`: Merges dict into user.facts
- `update_preferences`: Merges dict into user.preferences
- `add_skill`: Appends to user.skills (deduped)
- `remove_skill`: Removes from user.skills

**Backend**: Qdrant user_profiles
**Migration notes**: Not yet ported. Extends the simpler remember_user_fact/update_user_preference tools.

---

## Category 3: Document Management Tools (4 tools)

### 3.1 `list_session_docs`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| (none) | — | — | — | — |

**Implementation** (`mcp_server.py:1932–1958`):
```python
docs = await document_processor.get_session_documents(session_id)
# Returns: [{doc_id, filename, content_type, size, created_at, chunk_count}]
```

**Backend**: `document_processor.py` (ephemeral Qdrant collection)
**Migration notes**: CCA doesn't have ephemeral document storage yet. Consider if needed.

---

### 3.2 `upload_document`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `content` | string | Yes | — | Document content (text or base64) |
| `filename` | string | Yes | — | Original filename |
| `content_type` | string | No | auto-detect | MIME type |

**Implementation**: Chunks document → embeds → stores in Qdrant ephemeral_docs collection with session_id tag.
**Backend**: `document_processor.py` → Qdrant + Embedding server
**Migration notes**: Useful for "analyze this document" workflows.

---

### 3.3 `search_documents`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | — | Search query |
| `doc_id` | string | No | — | Search within specific document |
| `n_results` | integer | No | 5 | Results to return |

**Implementation**: Semantic search within ephemeral_docs collection, optionally filtered by doc_id.
**Backend**: Qdrant ephemeral_docs collection

---

### 3.4 `promote_doc_to_knowledge`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `doc_id` | string | Yes | — | Document to promote |
| `target` | enum | Yes | — | `"user"` or `"project"` |
| `project` | string | No | `"default"` | Target project name |
| `tags` | array[string] | No | — | Tags for categorization |

**Implementation** (`mcp_server.py:2036–2077`):
```python
# target="user" requires identified user
result = await document_processor.promote_to_knowledge(doc_id, target, user_id, tags, project)
```

**Backend**: Moves vectors from ephemeral_docs to user_*_knowledge or codebase_files collection
**Migration notes**: Requires the full document pipeline to be ported first.

---

## Category 4: Project Context Tools (3 tools)

### 4.1 `manage_project_context`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `action` | enum | Yes | — | `"get_active"`, `"set_active"`, `"list_all"`, `"create_new"` |
| `project_name` | string | No | — | For set_active/create_new |
| `description` | string | No | — | For create_new |
| `keywords` | array[string] | No | — | For create_new |

**Implementation** (`mcp_server.py:2080–2182`):
```python
# get_active: returns current project context from session
# set_active: validates project exists, switches session context
# list_all: returns all projects with descriptions, keywords, is_active
# create_new: creates project in registry from conversation context
```

**Backend**: `project_context.py` + `project_registry.py` (Redis + Nextcloud WebDAV)
**Migration notes**: CCA sessions may not need project switching if workspace-scoped.

---

### 4.2 `get_project_info`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project_name` | string | Yes | — | Project to look up |

**Implementation** (`mcp_server.py:2184–2218`):
```python
project = await project_ctx.registry.get_project(project_name)
# Returns: to_dict() with description, keywords, folder structure, relationships
# On not found: suggests similar_projects (fuzzy match), lists available_projects
```

**Backend**: `project_registry.py`

---

### 4.3 `list_codebase_files`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project` | string | No | — | Filter by project |
| `language` | string | No | — | Filter by language |

**Implementation** (`mcp_server.py:1960–2034`):
```python
unique_files = await memory.codebase_indexer.collection.get_unique_files()
# Returns dict: path → etag
# Groups by project (extracted from path: "EVA/code/file.ps1" → project "EVA")
# Language detection by extension: {ps1: powershell, py: python, sh: bash, ...}
```

**Backend**: Qdrant codebase_files collection metadata
**Migration notes**: Provides inventory of indexed code. Useful for code navigation.

---

## Category 5: File Operations — LLM-Callable (8 tools)

### 5.1 `read_file`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path (relative to workspace) |
| `encoding` | enum | No | `"utf-8"` | `"utf-8"` or `"base64"` |
| `start_line` | integer | No | -1 | Start line (-1 = beginning) |
| `end_line` | integer | No | -1 | End line (-1 = end) |
| `max_chars` | integer | No | — | Character limit |

**Implementation** (`mcp_server.py:2237–2349`):
```python
# Cascading fallback:
# 1. Local filesystem via mcp_tools._read_file()
# 2. Qdrant codebase index (reconstruct from chunks)
# 3. Nextcloud WebDAV via indexer.nextcloud.download_file()
```

**Backend**: Local FS → Qdrant → Nextcloud (3-tier fallback)
**Migration notes**: CCA already has `FileEditExtension` with read capability. May need the Qdrant/WebDAV fallback for indexed-only files.

---

### 5.2 `write_file`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path |
| `content` | string | Yes | — | New file content |

**Implementation** (`mcp_tools.py:569–586`):
```python
# Requires file to exist (use create_file for new files)
full_path.write_text(content, encoding="utf-8")
```

**Backend**: Local filesystem
**Migration notes**: CCA `FileEditExtension` already handles this.

---

### 5.3 `edit_file`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path |
| `search` | string | Yes | — | Exact text to find |
| `replace` | string | Yes | — | Replacement text |
| `replace_all` | boolean | No | false | Replace all occurrences or first only |

**Implementation** (`mcp_server.py:2383–2399`):
```python
content = file.read_text()
if replace_all:
    new_content = content.replace(search, replace)
else:
    new_content = content.replace(search, replace, 1)
file.write_text(new_content)
```

**Backend**: Local filesystem
**Migration notes**: CCA `FileEditExtension` already handles this with more sophisticated diff-based editing.

---

### 5.4 `create_file`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path |
| `content` | string | Yes | — | Initial content |
| `overwrite` | boolean | No | false | Overwrite if exists |
| `create_dirs` | boolean | No | true | Auto-create parent directories |

**Implementation** (`mcp_tools.py:539–567`):
```python
if full_path.exists() and not overwrite:
    raise FileExistsError(...)
if create_dirs:
    full_path.parent.mkdir(parents=True, exist_ok=True)
full_path.write_text(content, encoding="utf-8")
```

**Backend**: Local filesystem
**Migration notes**: CCA `FileEditExtension` handles this.

---

### 5.5 `move_file`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | Yes | — | Source path |
| `destination` | string | Yes | — | Destination path |

**Implementation** (`mcp_tools.py:463–495`):
```python
shutil.move(str(source_path), str(dest_path))
```

**Backend**: Local filesystem
**Migration notes**: Not in CCA's current extension set. Simple to add.

---

### 5.6 `list_directory` / `list_files`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | No | `"."` | Directory path |
| `recursive` | boolean | No | false | Recurse into subdirectories |
| `pattern` | string | No | — | Glob pattern filter |

**Implementation** (`mcp_tools.py:281–332`):
```python
for entry in sorted(target.iterdir()):
    if pattern and not fnmatch(entry.name, pattern):
        continue
    files.append({"path": str(entry.relative_to(workspace)), "type": "directory"|"file", "size": ...})
```

**Backend**: Local filesystem
**Security**: Path traversal validation
**Migration notes**: CCA `CommandLineExtension` can run `ls`. Dedicated tool may be cleaner.

---

### 5.7 `file_glob_search`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | string | Yes | — | Glob pattern (`"**/*.py"`, `"*.json"`) |
| `path` | string | No | `"."` | Starting directory |
| `max_results` | integer | No | 100 | Maximum matches |

**Implementation** (`mcp_server.py:2453–2536`):
```python
# Local glob with exclusions
excluded = {"node_modules", ".git", "__pycache__", ".venv", "venv", "build", "dist", ...}
matches = [p for p in Path(path).glob(pattern) if not any(ex in p.parts for ex in excluded)]

# Qdrant fallback: search codebase_files for file_path matches
if not matches:
    all_files = await codebase_indexer.collection.get_unique_files()
    matches = [f for f in all_files if fnmatch(f, pattern)]
```

**Backend**: Local filesystem + Qdrant fallback
**Migration notes**: CCA `FileEditExtension` has glob support.

---

### 5.8 `search_files_content`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `pattern` | string | Yes | — | Regex or literal text |
| `path` | string | No | workspace | Directory to search |
| `file_pattern` | string | No | — | Glob to filter files |
| `max_results` | integer | No | 50 | Maximum matches |

**Implementation** (`mcp_tools.py:950–1011`):
```python
regex = re.compile(pattern, re.IGNORECASE)
for file in Path(path).rglob("*"):
    if file.suffix in BINARY_EXTENSIONS:  # .exe, .dll, .so, .bin, .png, .jpg, .gif, .pdf
        continue
    for line_num, line in enumerate(file.read_text().splitlines(), 1):
        if regex.search(line):
            matches.append({"file": str(file), "line": line_num, "content": line[:200]})
```

**Backend**: Local filesystem (regex search)
**Migration notes**: CCA `FileEditExtension` has search capability. Verify regex support.

---

## Category 6: Shell Execution (1 tool)

### 6.1 `execute_command`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `command` | string | Yes | — | Shell command |
| `cwd` | string | No | workspace | Working directory |
| `timeout` | integer | No | 30 | Seconds (max enforced) |

**Implementation** (`mcp_tools.py:830–897`):
```python
# Security validation blocks:
BLOCKED_PATTERNS = [
    "rm -rf /", "dd if=", "mkfs.",           # Destructive
    "sudo", "su ", "pkexec",                   # Privilege escalation
    "wget", "curl https://", "nc ", "nmap",    # Network tools
    ":() { :",                                  # Fork bombs
    # Command injection after: ; | ` $( && ||
    # Output redirect to: /etc, /dev, /proc, /sys, /usr, /bin, /sbin
]

# Environment sanitized: PASSWORD, SECRET, KEY, TOKEN, CREDENTIAL vars redacted
proc = await asyncio.create_subprocess_shell(command, cwd=cwd, env=safe_env, ...)
stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
```

**Backend**: Shell subprocess
**Security**: Pattern-based command blocking + environment redaction
**Migration notes**: CCA already has `CommandLineExtension` with its own security model (`get_allowed_commands()`). Compare security approaches — CCA uses an allowlist, MCP uses a blocklist.

---

## Category 7: Git Tools (1 tool)

### 7.1 `view_diff`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `staged` | boolean | No | false | Show staged vs unstaged |
| `file_path` | string | No | — | Specific file or all |
| `include_status` | boolean | No | true | Include git status summary |

**Implementation** (`mcp_server.py:2538–2606`):
```python
cmd = ["git", "diff"]
if staged:
    cmd.append("--cached")
if file_path:
    cmd.extend(["--", file_path])

# Optional git status --porcelain parsing:
# staged: M/A/D/R (first char != space)
# unstaged: M/D/R (second char != space)
# untracked: ?? (both chars)
```

**Backend**: Git subprocess
**Migration notes**: CCA `CommandLineExtension` can run git commands. Dedicated tool provides structured output.

---

## Category 8: Code Intelligence / Graph Tools (3 tools)

### 8.1 `query_call_graph`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `function_name` | string | Yes | — | Function to query |
| `query_type` | enum | Yes | — | `"callers"`, `"callees"`, `"call_chain"` |
| `project` | string | No | — | Filter by project |
| `file_path` | string | No | — | Disambiguate same-name functions |
| `depth` | integer | No | 3 | For call_chain (1–10) |
| `direction` | enum | No | `"out"` | `"in"` or `"out"` for call_chain |
| `limit` | integer | No | 20 | Max results |

**Implementation** (`mcp_server.py:2894–2942`):
```python
await memory.graph_adapter.heartbeat()  # verify Memgraph up
if query_type == "callers":
    results = await graph_adapter.get_callers(function_name, project, file_path, limit)
elif query_type == "callees":
    results = await graph_adapter.get_callees(function_name, project, file_path, limit)
elif query_type == "call_chain":
    results = await graph_adapter.get_call_chain(function_name, depth, direction, project, limit)
```

**Backend**: Memgraph (192.168.4.202:7687) via `memgraph_adapter.py`
**Migration notes**: Requires Memgraph client. Pure query tool — easy to port.

---

### 8.2 `find_orphan_functions`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `project` | string | No | — | Filter by project |
| `language` | string | No | — | Filter by language |
| `limit` | integer | No | 50 | Max results |

**Implementation** (`mcp_server.py:2944–3004`):
```python
# Cypher: MATCH (fn:Function)-[:DEFINED_IN]->(:File) WHERE NOT ()-[:CALLS]->(fn)
# Excludes: main, __init__, __main__, functions starting with _
# Returns: name, qualified_name, file_path, language, project, signature, line_start
```

**Backend**: Memgraph (Cypher query)
**Migration notes**: Single Cypher query — straightforward.

---

### 8.3 `analyze_dependencies`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_path` | string | No | — | File to analyze (either this or function_name required) |
| `function_name` | string | No | — | Function to analyze |
| `project` | string | No | — | Filter results |
| `limit` | integer | No | 20 | Max results |

**Implementation** (`mcp_server.py:3006–3069`):
```python
if file_path:
    functions = await graph_adapter.get_file_functions(file_path)
    deps = await graph_adapter.get_cross_file_deps(file_path, limit)
    # Returns: functions_in_file, dependent_files, dependent_file_count
elif function_name:
    callers = await graph_adapter.get_callers(function_name)
    callees = await graph_adapter.get_callees(function_name)
    # Returns: callers, callees, unique_caller_files, unique_callee_files
```

**Backend**: Memgraph
**Migration notes**: Combines multiple graph queries. Consider splitting into smaller tools.

---

## Category 9: Rules System Tools (4 tools)

### 9.1 `create_rule_block`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | Yes | — | Rule name (`"python-style"`, `"api-error-handling"`) |
| `rule` | string | Yes | — | Rule content/instructions |
| `rule_type` | enum | Yes | — | `"always"`, `"auto_attached"`, `"agent_requested"`, `"manual"` |
| `description` | string | No | — | Required for `agent_requested` type |
| `globs` | array[string] | No | — | Required for `auto_attached` (`["*.py", "src/**"]`) |
| `regex` | string | No | — | Alternative to globs for `auto_attached` |
| `global_rule` | boolean | No | false | Shared with all users |

**Implementation** (`mcp_server.py:2692–2753`):
```python
# Validation: agent_requested REQUIRES description, auto_attached REQUIRES globs or regex
rule = Rule(id=uuid4(), name=name, rule=rule, rule_type=rule_type, ...)
await rules_collection.store_rule(rule)
```

**Backend**: Qdrant (rules collection with semantic embeddings)
**Migration notes**: CCA doesn't have a rules system. Assess whether needed for HTTP mode.

---

### 9.2 `request_rule`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | No | — | Semantic search by description |
| `name` | string | No | — | Exact name match |
| `file_path` | string | No | — | Get auto_attached rules for file |
| `include_global` | boolean | No | true | Include global rules |

**Backend**: Qdrant rules collection (exact + semantic search)

---

### 9.3 `list_rules`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `rule_type` | enum | No | — | Filter by type |
| `include_global` | boolean | No | true | Include global rules |

**Backend**: Qdrant rules collection

---

### 9.4 `delete_rule`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `rule_id` | string | No | — | Rule ID |
| `name` | string | No | — | Rule name (looks up ID) |

**Security**: Ownership check — can only delete your own or global rules
**Backend**: Qdrant rules collection

---

## Category 10: Vision (1 tool)

### 10.1 `analyze_image`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image_url` | string | Yes | — | Image URL or base64 data URI |
| `prompt` | string | No | `"Describe this image in detail"` | Analysis prompt |

**Implementation**: HTTP POST to Vision server with image + prompt
**Backend**: Qwen3-VL-30B at Spark1:8300
**Migration notes**: Simple HTTP call. Easy to port.

---

## Category 11: MCP-Protocol-Only Tools (5 tools)

These are in `mcp_tools.py` and exposed only via MCP JSON-RPC, NOT available to the LLM:

### 11.1 `copy_file`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source` | string | Yes | — | Source path |
| `destination` | string | Yes | — | Destination path |

**Implementation** (`mcp_tools.py:497–537`):
```python
shutil.copy2(str(source_path), str(dest_path))  # preserves metadata
```

---

### 11.2 `replace_lines`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path |
| `start_line` | integer | Yes | — | Start line (1-indexed) |
| `end_line` | integer | Yes | — | End line (inclusive) |
| `content` | string | Yes | — | Replacement content |

**Implementation** (`mcp_tools.py:589–625`):
```python
lines = file.read_text().splitlines(keepends=True)
lines[start_line-1:end_line] = [content + "\n"]
file.write_text("".join(lines))
```

---

### 11.3 `insert_lines`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path |
| `line` | integer | Yes | — | Line to insert at (1-indexed) |
| `content` | string | Yes | — | Content to insert |

**Implementation** (`mcp_tools.py:627–661`):
```python
lines = file.read_text().splitlines(keepends=True)
lines.insert(line-1, content + "\n")
file.write_text("".join(lines))
```

---

### 11.4 `search_replace`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `path` | string | Yes | — | File path |
| `search` | string | Yes | — | Text to find |
| `replace` | string | Yes | — | Replacement text |
| `use_regex` | boolean | No | false | Use regex matching |

**Implementation** (`mcp_tools.py:663–710`):
```python
if use_regex:
    new_content, count = re.subn(search, replace, content)
else:
    count = content.count(search)
    new_content = content.replace(search, replace)
```

---

### 11.5 `move_file` (MCP variant)

Duplicate of LLM-callable version. Same implementation via `shutil.move()`.

---

## Tool Recovery Suggestions

When a tool fails, the MCP server returns recovery hints from `TOOL_RECOVERY_SUGGESTIONS`:

| Tool | Recovery Suggestion |
|------|-------------------|
| `search_knowledge` | Try broader keywords, check spelling, try different tiers |
| `web_search` | Simplify the query, remove special characters |
| `identify_user` | Ask the user directly: "What name should I use for you?" |
| `search_memory` | Try different collection types, broader search terms |
| `read_file` | Check path exists, try list_files first |
| `execute_command` | Check command syntax, verify working directory |
| `search_codebase` | Try different language filter, broader query |
| `query_call_graph` | Verify function name spelling, try without project filter |

---

## External Service Dependency Map

```
┌─────────────────────────────────────────────────────────────────┐
│                     Tool → Service Matrix                        │
├──────────────────┬──────┬────────┬─────────┬──────────┬─────────┤
│ Tool             │Redis │Qdrant  │Embedding│Memgraph  │SearXNG  │
├──────────────────┼──────┼────────┼─────────┼──────────┼─────────┤
│ search_memory    │  ✓   │  ✓     │  ✓      │          │         │
│ web_search       │      │        │         │          │  ✓      │
│ search_knowledge │      │  ✓     │  ✓      │  ✓       │         │
│ search_codebase  │      │  ✓     │  ✓      │  ✓       │         │
│ fetch_url        │      │        │         │          │         │
│ identify_user    │  ✓   │  ✓     │  ✓      │          │         │
│ infer_user       │  ✓   │  ✓     │  ✓      │          │         │
│ remember_fact    │  ✓   │  ✓     │         │          │         │
│ update_pref      │  ✓   │  ✓     │         │          │         │
│ get_user_context │  ✓   │  ✓     │         │          │         │
│ manage_profile   │      │  ✓     │         │          │         │
│ upload_document  │      │  ✓     │  ✓      │          │         │
│ search_documents │      │  ✓     │  ✓      │          │         │
│ promote_doc      │      │  ✓     │  ✓      │          │         │
│ manage_project   │  ✓   │        │         │          │         │
│ get_project_info │  ✓   │        │         │          │         │
│ list_codebase    │      │  ✓     │         │          │         │
│ query_call_graph │      │        │         │  ✓       │         │
│ find_orphans     │      │        │         │  ✓       │         │
│ analyze_deps     │      │        │         │  ✓       │         │
│ create_rule      │      │  ✓     │  ✓      │          │         │
│ request_rule     │      │  ✓     │  ✓      │          │         │
│ analyze_image    │      │        │         │          │         │
│ File ops (8)     │      │        │         │          │         │
│ execute_command  │      │        │         │          │         │
│ view_diff        │      │        │         │          │         │
├──────────────────┼──────┼────────┼─────────┼──────────┼─────────┤
│ Service URL      │:6379 │:6333   │:8200    │:7687     │:8888    │
│ Host             │Spark1│Spark1  │Spark1   │node3     │Spark1   │
└──────────────────┴──────┴────────┴─────────┴──────────┴─────────┘

Additional services:
- Vision: Spark1:8300 (analyze_image only)
- vLLM: Spark2:8000 (agent loop LLM, not a tool backend)
- Nextcloud WebDAV: node4 (read_file fallback, codebase indexing)
```

---

## Migration Priority Recommendation

### Already Ported (5 tools)
- `identify_user` — in `tools_extension.py`
- `infer_user` — in `tools_extension.py`
- `remember_user_fact` — in `tools_extension.py`
- `update_user_preference` — in `tools_extension.py`
- `get_user_context` — in `tools_extension.py`

### Already Covered by CCA Extensions (8 tools)
CCA's built-in extensions handle these — no migration needed:
- `read_file` → `FileEditExtension`
- `write_file` → `FileEditExtension`
- `edit_file` → `FileEditExtension`
- `create_file` → `FileEditExtension`
- `search_files_content` → `FileEditExtension`
- `file_glob_search` → `FileEditExtension`
- `execute_command` → `CommandLineExtension`
- `list_directory` → `CommandLineExtension` (via `ls`)

### Priority 1 — High Value, Low Effort (5 tools)
Pure HTTP calls, no complex state:
- `web_search` — SearXNG HTTP call (~50 lines)
- `fetch_url_content` — httpx + BeautifulSoup (~80 lines)
- `view_diff` — git subprocess (~60 lines)
- `analyze_image` — Vision server HTTP call (~30 lines)
- `manage_user_profile` — extends existing user tools (~40 lines)

### Priority 2 — High Value, Medium Effort (6 tools)
Require Qdrant/Memgraph client setup:
- `search_knowledge` — Qdrant unified search (~100 lines)
- `search_memory` — Redis + Qdrant search (~60 lines)
- `query_call_graph` — Memgraph queries (~50 lines)
- `find_orphan_functions` — Memgraph Cypher (~40 lines)
- `analyze_dependencies` — Memgraph multi-query (~60 lines)
- `search_codebase` — Qdrant codebase search (~50 lines)

### Priority 3 — Medium Value, Higher Effort (6 tools)
Require full subsystem ports:
- `upload_document` — needs document processor pipeline
- `search_documents` — needs ephemeral doc storage
- `list_session_docs` — needs ephemeral doc storage
- `promote_doc_to_knowledge` — needs full document pipeline

### Priority 4 — Low Priority (4 tools)
Rules system — assess if needed for CCA:
- `create_rule_block`
- `request_rule`
- `list_rules`
- `delete_rule`

### Skip — MCP-Protocol-Only (5 tools)
Not needed in CCA (handled by FileEditExtension):
- `copy_file`
- `replace_lines`
- `insert_lines`
- `search_replace`
- `move_file` (MCP variant)

### Skip — Covered Differently (3 tools)
- `manage_project_context` — CCA is workspace-scoped
- `get_project_info` — CCA is workspace-scoped
- `reindex_codebase` — Infrastructure concern, not agent tool

---

## Source File Reference

| File | Location | Lines | Content |
|------|----------|-------|---------|
| Tool definitions | `nvidia-dgx-spark/mcp-server/mcp_server.py` | 351–1213 | `AVAILABLE_TOOLS` list |
| Tool dispatch | `nvidia-dgx-spark/mcp-server/mcp_server.py` | 1415–3100 | `execute_tool()` function |
| Recovery hints | `nvidia-dgx-spark/mcp-server/mcp_server.py` | 1227–1254 | `TOOL_RECOVERY_SUGGESTIONS` |
| Client-handled set | `nvidia-dgx-spark/mcp-server/mcp_server.py` | 334–344 | `MCP_CLIENT_HANDLED_TOOLS` |
| MCP tools manager | `nvidia-dgx-spark/mcp-server/mcp_tools.py` | 121–1046 | `MCPToolsManager` class |
| MCP protocol handler | `nvidia-dgx-spark/mcp-server/mcp_tools.py` | 1052–1159 | `MCPProtocolHandler` |
| Session manager | `nvidia-dgx-spark/mcp-server/session_manager.py` | 1–2423 | User identification |
| Memory manager | `nvidia-dgx-spark/mcp-server/memory_manager.py` | 1–1143 | Memory tiers + CriticalFacts |
| Knowledge search | `nvidia-dgx-spark/mcp-server/knowledge_search.py` | 1–598 | Unified search |
| CCA user tools | `nvidia-dgx-spark/cca/confucius/server/user/tools_extension.py` | — | 5 tools already ported |
