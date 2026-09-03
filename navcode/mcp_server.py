"""navcode MCP server — exposes codebase intelligence to AI agents via MCP protocol."""

from pathlib import Path

from fastmcp import FastMCP

from navcode.retriever import ContextRetriever

mcp = FastMCP("navcode")
PROJECT_ROOT = Path.cwd()
retriever = ContextRetriever(PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Tool 1 — get_context
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_get_context(task: str, scope: str = "auto") -> str:
    """
    Get relevant code context for a task.

    Call this FIRST before reading any files.
    Returns only the code you need — nothing more.

    Args:
        task: Describe what you need to do in plain English
              e.g. "fix the login timeout bug"
              e.g. "add rate limiting to the API"
        scope: "auto" (recommended) or force:
               "surgical" / "local" / "connected" / "architectural"

    Returns:
        Markdown-formatted context with relevant code chunks
    """
    result = retriever.get_context(task)
    return retriever.format_for_agent(result)


# ---------------------------------------------------------------------------
# Tool 2 — expand_context
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_expand_context(file_path: str, reason: str) -> str:
    """
    Get full context for a specific file.

    Call this when get_context did not return enough
    from a specific file you need more of.

    Args:
        file_path: Relative path to the file
                   e.g. "navcode/auth.py"
        reason: Why you need more context
                e.g. "need to see all DB models"

    Returns:
        All symbols from the file as markdown
    """
    from navcode.retriever import FileContext  # noqa: F401 — confirm type available

    file_ctx = retriever.expand_context(file_path, reason)

    lines = [f"## Expanded: {file_path}\n"]
    for sym in file_ctx.symbols:
        lines.append(
            f"### {sym.symbol_type}: {sym.name} "
            f"(lines {sym.line_start}-{sym.line_end})"
        )
        lines.append(f"```{file_ctx.language or ''}")
        lines.append(sym.content)
        lines.append("```\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3 — get_callers
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_get_callers(function_name: str) -> str:
    """
    Find all functions that call a specific function.

    Use this to understand the blast radius of a change.

    Args:
        function_name: Name of the function
                       e.g. "authenticate_user"

    Returns:
        List of callers with file paths and line numbers
    """
    callers = retriever.graph.get_callers(function_name)
    if not callers:
        return f"No callers found for `{function_name}`."

    lines = [f"## Callers of `{function_name}`\n"]
    for c in callers:
        lines.append(
            f"- `{c['function_name']}` "
            f"in `{c['file_path']}` "
            f"line {c['line_start']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 4 — get_deps
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_get_deps(file_path: str) -> str:
    """
    Get all files that this file depends on (imports).

    Use this to understand what else might be affected
    before making changes to a file.

    Args:
        file_path: Relative path to file
                   e.g. "navcode/auth.py"

    Returns:
        List of dependency file paths
    """
    deps = retriever.graph.get_file_deps(file_path)
    dependents = retriever.graph.get_file_dependents(file_path)

    lines = [f"## Dependencies for `{file_path}`\n"]
    lines.append("### This file imports:")
    if deps:
        for d in deps:
            lines.append(f"  - `{d}`")
    else:
        lines.append("  - none found")

    lines.append("\n### Files that import this file:")
    if dependents:
        for d in dependents:
            lines.append(f"  - `{d}`")
    else:
        lines.append("  - none found")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 5 — search
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_search(query: str, limit: int = 10) -> str:
    """
    Semantic + keyword search across the entire codebase.

    Use this when you need to find where something is defined
    or used across the codebase.

    Args:
        query: What to search for
               e.g. "database connection", "auth token", "rate limit"
        limit: Max results (default 10, max 20)

    Returns:
        Matching code chunks with file paths and line numbers
    """
    limit = min(limit, 20)
    results = retriever.indexer.hybrid_search(query, limit=limit)

    if not results:
        return f"No results found for `{query}`."

    lines = [f"## Search results for `{query}`\n"]
    for r in results:
        score = round(r.get("score", 0), 3)
        lines.append(
            f"### `{r['path']}` — "
            f"{r['symbol_type']}: `{r['symbol_name']}` "
            f"(lines {r['line_start']}-{r['line_end']}) "
            f"score: {score}"
        )
        lines.append(f"```{r.get('language', '')}")
        lines.append(r["content"])
        lines.append("```\n")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 6 — get_structure
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_get_structure() -> str:
    """
    Get high-level project structure and architecture map.

    Use this for architectural tasks or when you need to
    understand the overall project before diving in.

    Returns:
        Project overview: entry points, hotspot files,
        language breakdown, stats
    """
    structure = retriever.get_structure()

    lines = ["## Project Structure\n"]

    lines.append(f"**Files:** {structure['total_files']}  ")
    lines.append(f"**Symbols:** {structure['total_symbols']}  ")
    lines.append(f"**Est. tokens:** {structure['total_tokens_estimate']}\n")

    lines.append("### Language Breakdown")
    for lang, count in structure["language_breakdown"].items():
        lines.append(f"  - {lang}: {count} files")

    lines.append("\n### Entry Points")
    for ep in structure["entry_points"][:10]:
        lines.append(f"  - `{ep}`")

    lines.append("\n### Most Depended-On Files")
    for hf in structure["hotspot_files"][:10]:
        lines.append(f"  - `{hf['file_path']}` ({hf['dependent_count']} dependents)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 7 — stats
# ---------------------------------------------------------------------------


@mcp.tool()
def navcode_stats() -> str:
    """
    Show navcode index statistics and token savings.

    Returns:
        Index health, file counts, estimated token savings
    """
    stats = retriever.indexer.get_stats()

    lines = ["## navcode stats\n"]
    lines.append(f"**Indexed files:** {stats.get('file_count', 0)}")
    lines.append(f"**Total symbols:** {stats.get('symbol_count', 0)}")
    lines.append(f"**DB size:** {stats.get('db_size_kb', 0)} KB")
    lines.append(
        f"**Watcher:** {'running' if stats.get('watcher_running') else 'stopped'}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def serve(project_root: Path = None) -> None:
    """Start the navcode MCP server."""
    global PROJECT_ROOT, retriever
    if project_root:
        PROJECT_ROOT = project_root
        retriever = ContextRetriever(PROJECT_ROOT)
    mcp.run()
