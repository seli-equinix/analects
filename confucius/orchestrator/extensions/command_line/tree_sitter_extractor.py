# Copyright (c) Meta Platforms, Inc. and affiliates.
# pyre-strict
"""Tree-sitter based bash command extraction.

Replaces bashlex for parsing bash commands and extracting command names
with their arguments. Handles heredocs, pipelines, compound commands,
and all bash constructs that bashlex fails on.

Uses tree-sitter-bash v0.20.5 (already compiled in Docker image at
/usr/local/lib/tree-sitter-languages.so).
"""
from __future__ import annotations

import logging
import re
import shlex
from typing import Optional

from tree_sitter import Language, Node, Parser

logger: logging.Logger = logging.getLogger(__name__)

# Path to built language library (same as code_intelligence/tree_sitter_parser.py)
LANGUAGE_LIBRARY_PATH = "/usr/local/lib/tree-sitter-languages.so"

# Module-level singletons (lazy init)
_parser: Optional[Parser] = None
_language: Optional[Language] = None
_query = None  # Compiled query (cached)

# Node types that represent word-like tokens (arguments / command parts)
_WORD_TYPES = frozenset(
    {
        "word",
        "string",
        "raw_string",
        "simple_expansion",
        "expansion",
        "concatenation",
        "command_substitution",
        "number",
    }
)

# Node types that terminate argument collection (redirections)
_STOP_TYPES = frozenset(
    {
        "file_redirect",
        "heredoc_redirect",
        "herestring_redirect",
    }
)

# tree-sitter query: matches ALL command nodes anywhere in the AST —
# inside pipelines, lists, compound commands, loops, case statements,
# subshells, and heredoc-bearing commands.
_COMMAND_QUERY = "(command name: (command_name) @cmd_name) @cmd"


def _get_parser() -> tuple[Parser, Language]:
    """Lazy-initialize the tree-sitter bash parser (module-level singleton)."""
    global _parser, _language
    if _parser is not None and _language is not None:
        return _parser, _language

    _language = Language(LANGUAGE_LIBRARY_PATH, "bash")
    _parser = Parser()
    _parser.set_language(_language)
    logger.debug("tree-sitter bash parser initialized")
    return _parser, _language


def _get_query():
    """Get or compile the command extraction query (cached)."""
    global _query
    if _query is not None:
        return _query

    _, language = _get_parser()
    _query = language.query(_COMMAND_QUERY)
    return _query


def _extract_command_tokens(command_node: Node) -> list[str]:
    """Extract command name and arguments from a tree-sitter command node.

    Collects the command_name text followed by word-like children,
    stopping at redirections. Skips leading variable_assignment nodes
    (e.g. ``ENV=prod python app.py``).

    Returns a list like ``["git", "commit", "-m", "message"]``.
    """
    tokens: list[str] = []

    for child in command_node.children:
        if child.type == "command_name":
            text = child.text
            if text:
                tokens.append(text.decode("utf8"))
        elif child.type == "variable_assignment":
            # Skip VAR=value prefixes
            continue
        elif child.type in _WORD_TYPES:
            text = child.text
            if text:
                decoded = text.decode("utf8")
                # Strip surrounding quotes from string / raw_string nodes
                if child.type == "string":
                    decoded = decoded.strip('"')
                elif child.type == "raw_string":
                    decoded = decoded.strip("'")
                tokens.append(decoded)
        elif child.type in _STOP_TYPES:
            # Hit a redirection — stop collecting arguments
            break
        elif tokens:
            # Unknown non-word node after command started — skip
            continue

    return tokens


def extract_commands_tree_sitter(command: str) -> list[list[str]]:
    """Parse a bash command string and extract all commands with arguments.

    Uses tree-sitter-bash for robust parsing that handles heredocs,
    pipelines, process substitution, and all bash constructs.

    Args:
        command: A bash command string (may contain pipes, &&, ||,
                 loops, heredocs, etc.)

    Returns:
        ``list[list[str]]`` where each inner list is
        ``[command_name, arg1, arg2, ...]``.

    Returns an empty list on parse failure (never raises).
    """
    parser, _ = _get_parser()
    query = _get_query()

    tree = parser.parse(bytes(command, "utf8"))
    root = tree.root_node

    if root.has_error:
        logger.debug(
            "tree-sitter parsed with errors (partial results): %s",
            command[:100],
        )

    commands: list[list[str]] = []
    captures = query.captures(root)

    for node, capture_name in captures:
        if capture_name == "cmd":
            tokens = _extract_command_tokens(node)
            if tokens:
                commands.append(tokens)

    return commands


def fallback_extract_commands(command: str) -> list[list[str]]:
    """Regex/shlex fallback when tree-sitter is unavailable.

    Used when the ``.so`` library is not loaded (e.g. local dev outside
    Docker).  Strips heredoc content, splits on command separators, and
    uses :func:`shlex.split` for quote-aware tokenization.  Falls back
    to whitespace splitting if shlex also fails.

    This is intentionally simple — we only need command names for the
    allowed/disallowed validation check.  The actual execution is handled
    by subprocess which supports all bash syntax.
    """
    # Strip heredoc content before tokenizing.
    # Match <<MARKER ... MARKER (with content between)
    cleaned = re.sub(
        r"<<-?\s*['\"]?(\w+)['\"]?\s*\n.*?\n\1\b",
        "",
        command,
        flags=re.DOTALL,
    )
    # Match <<MARKER to end-of-string (unterminated heredoc)
    cleaned = re.sub(
        r"<<-?\s*['\"]?\w+['\"]?\s*\n.*",
        "",
        cleaned,
        flags=re.DOTALL,
    )
    # Heredoc on same line with no newline content
    cleaned = re.sub(r"<<-?\s*['\"]?\w+['\"]?\s*$", "", cleaned)

    if not cleaned.strip():
        # Entire command was heredoc — extract command before <<
        match = re.match(r"\s*(\S+)", command)
        return [[match.group(1)]] if match else []

    # Try shlex for proper quote handling
    try:
        tokens = shlex.split(cleaned)
    except ValueError:
        # shlex can fail on unmatched quotes — just split on spaces
        tokens = cleaned.split()

    if not tokens:
        return []

    # Split token list on command separators
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in ("&&", "||", ";", "|"):
            if current:
                commands.append(current)
                current = []
        else:
            current.append(token)
    if current:
        commands.append(current)

    # Last resort: get first word from the original command
    if not commands:
        first = command.strip().split()[0] if command.strip() else ""
        if first:
            commands.append([first])

    return commands
