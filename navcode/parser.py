"""AST-based symbol extractor for navcode.

Parses source files with tree-sitter and emits a flat list of
:class:`Symbol` objects that the indexer stores in FTS5.

Supported languages (27):
  python, javascript, typescript, jsx, tsx, java, c, cpp, csharp,
  go, rust, ruby, php, swift, kotlin, scala, haskell, lua, r, bash,
  html, css, json, yaml, toml, markdown, sql, dockerfile, xml,
  text, config, regex

Fallback rule
  Any language without a tree-sitter grammar, or any file where
  parsing fails, is chunked into 50-line blocks with
  ``symbol_type="chunk"``.  This function never raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Symbol:
    """A single extracted symbol (or content chunk) from a source file.

    Attributes:
        path: POSIX-relative path of the source file.
        symbol_name: Human-readable identifier for the symbol.
        symbol_type: One of ``function``, ``class``, ``import``,
            ``variable``, or ``chunk``.
        line_start: 1-based start line inside the file.
        line_end: 1-based end line (inclusive).
        content: Raw source text for this symbol.
    """

    path: str
    symbol_name: str
    symbol_type: str
    line_start: int
    line_end: int
    content: str


# ---------------------------------------------------------------------------
# Tree-sitter grammar loader
# ---------------------------------------------------------------------------

# Languages that map directly to a ``tree_sitter_<name>`` package
_TS_MODULE_MAP: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "jsx": "tree_sitter_javascript",   # shares grammar
    "tsx": "tree_sitter_typescript",   # shares grammar
    "java": "tree_sitter_java",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "csharp": "tree_sitter_c_sharp",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "ruby": "tree_sitter_ruby",
    "php": "tree_sitter_php",
    "swift": "tree_sitter_swift",
    "kotlin": "tree_sitter_kotlin",
    "scala": "tree_sitter_scala",
    "haskell": "tree_sitter_haskell",
    "lua": "tree_sitter_lua",
    "r": "tree_sitter_r",
    "bash": "tree_sitter_bash",
    "html": "tree_sitter_html",
    "css": "tree_sitter_css",
    "json": "tree_sitter_json",
    "yaml": "tree_sitter_yaml",
    "toml": "tree_sitter_toml",
    "markdown": "tree_sitter_markdown",
    "sql": "tree_sitter_sql",
    "dockerfile": "tree_sitter_dockerfile",
    "regex": "tree_sitter_regex",
}

# Cache loaded Language objects so we pay the import cost only once
_LANGUAGE_CACHE: dict[str, Any] = {}


def _load_language(lang: str) -> Any | None:
    """Import and return the tree-sitter Language for *lang*.

    Returns None if the grammar package is unavailable or the
    language is not managed by tree-sitter.
    """
    if lang in _LANGUAGE_CACHE:
        return _LANGUAGE_CACHE[lang]

    module_name = _TS_MODULE_MAP.get(lang)
    if module_name is None:
        _LANGUAGE_CACHE[lang] = None
        return None

    try:
        import importlib

        import tree_sitter  # noqa: F401 — confirms tree-sitter core is installed

        mod = importlib.import_module(module_name)
        # Each tree-sitter language pack exposes language() → Language
        language = mod.language()
        from tree_sitter import Language as TSLanguage

        ts_lang = TSLanguage(language)
        _LANGUAGE_CACHE[lang] = ts_lang
        return ts_lang
    except Exception as exc:
        logger.debug("tree-sitter grammar for '{}' unavailable: {}", lang, exc)
        _LANGUAGE_CACHE[lang] = None
        return None


def _parse_tree(source: bytes, lang: str) -> Any | None:
    """Return a tree-sitter Tree or None on failure."""
    ts_lang = _load_language(lang)
    if ts_lang is None:
        return None
    try:
        from tree_sitter import Parser

        parser = Parser(ts_lang)
        return parser.parse(source)
    except Exception as exc:
        logger.debug("Parsing failed for lang='{}': {}", lang, exc)
        return None


# ---------------------------------------------------------------------------
# Generic fallback chunker
# ---------------------------------------------------------------------------


def _fallback_chunks(
    lines: list[str],
    path: str,
    chunk_size: int = 50,
) -> list[Symbol]:
    """Split *lines* into fixed-size blocks and return as ``chunk`` symbols."""
    symbols: list[Symbol] = []
    total = len(lines)
    for start in range(0, max(total, 1), chunk_size):
        end = min(start + chunk_size, total)
        content = "".join(lines[start:end])
        symbols.append(
            Symbol(
                path=path,
                symbol_name=f"chunk_{start + 1}",
                symbol_type="chunk",
                line_start=start + 1,
                line_end=end,
                content=content,
            )
        )
    return symbols


# ---------------------------------------------------------------------------
# Node-type → symbol-type tables per language
# ---------------------------------------------------------------------------

# Each entry: node_type → symbol_type
# name_field gives the child field that carries the symbol identifier

_PYTHON_NODES: dict[str, str] = {
    "function_definition": "function",
    "async_function_definition": "function",
    "class_definition": "class",
    "import_statement": "import",
    "import_from_statement": "import",
    "assignment": "variable",
}

_JAVASCRIPT_NODES: dict[str, str] = {
    "function_declaration": "function",
    "function_expression": "function",
    "arrow_function": "function",
    "method_definition": "function",
    "class_declaration": "class",
    "import_statement": "import",
    "variable_declaration": "variable",
    "lexical_declaration": "variable",
}

_TYPESCRIPT_NODES: dict[str, str] = {
    **_JAVASCRIPT_NODES,
    "interface_declaration": "class",
    "type_alias_declaration": "class",
    "enum_declaration": "class",
    "abstract_class_declaration": "class",
}

_JAVA_NODES: dict[str, str] = {
    "method_declaration": "function",
    "constructor_declaration": "function",
    "class_declaration": "class",
    "interface_declaration": "class",
    "enum_declaration": "class",
    "import_declaration": "import",
    "field_declaration": "variable",
}

_C_NODES: dict[str, str] = {
    "function_definition": "function",
    "struct_specifier": "class",
    "enum_specifier": "class",
    "typedef_declaration": "class",
    "preproc_include": "import",
    "preproc_define": "variable",
}

_CPP_NODES: dict[str, str] = {
    **_C_NODES,
    "class_specifier": "class",
    "function_declarator": "function",
    "namespace_definition": "class",
    "template_declaration": "function",
}

_CSHARP_NODES: dict[str, str] = {
    "method_declaration": "function",
    "constructor_declaration": "function",
    "class_declaration": "class",
    "interface_declaration": "class",
    "struct_declaration": "class",
    "enum_declaration": "class",
    "using_directive": "import",
    "field_declaration": "variable",
    "property_declaration": "variable",
}

_GO_NODES: dict[str, str] = {
    "function_declaration": "function",
    "method_declaration": "function",
    "type_declaration": "class",
    "import_declaration": "import",
    "var_declaration": "variable",
    "const_declaration": "variable",
    "short_var_declaration": "variable",
}

_RUST_NODES: dict[str, str] = {
    "function_item": "function",
    "impl_item": "class",
    "struct_item": "class",
    "enum_item": "class",
    "trait_item": "class",
    "use_declaration": "import",
    "const_item": "variable",
    "static_item": "variable",
    "let_declaration": "variable",
    "mod_item": "class",
}

_RUBY_NODES: dict[str, str] = {
    "method": "function",
    "singleton_method": "function",
    "class": "class",
    "module": "class",
    "call": "import",
    "assignment": "variable",
}

_PHP_NODES: dict[str, str] = {
    "function_definition": "function",
    "method_declaration": "function",
    "class_declaration": "class",
    "interface_declaration": "class",
    "trait_declaration": "class",
    "namespace_use_declaration": "import",
}

_SWIFT_NODES: dict[str, str] = {
    "function_declaration": "function",
    "class_declaration": "class",
    "struct_declaration": "class",
    "protocol_declaration": "class",
    "enum_declaration": "class",
    "import_declaration": "import",
    "variable_declaration": "variable",
}

_KOTLIN_NODES: dict[str, str] = {
    "function_declaration": "function",
    "class_declaration": "class",
    "object_declaration": "class",
    "interface_declaration": "class",
    "import_header": "import",
    "property_declaration": "variable",
}

_SCALA_NODES: dict[str, str] = {
    "function_definition": "function",
    "class_definition": "class",
    "object_definition": "class",
    "trait_definition": "class",
    "import_declaration": "import",
    "val_definition": "variable",
}

_HASKELL_NODES: dict[str, str] = {
    "function": "function",
    "type_class": "class",
    "data_declaration": "class",
    "import": "import",
}

_LUA_NODES: dict[str, str] = {
    "function_declaration": "function",
    "local_function": "function",
    "assignment_statement": "variable",
}

_R_NODES: dict[str, str] = {
    "function_definition": "function",
    "left_assignment": "variable",
    "library_call": "import",
}

_BASH_NODES: dict[str, str] = {
    "function_definition": "function",
    "variable_assignment": "variable",
    "command": "import",   # source / . calls
}

_CSS_NODES: dict[str, str] = {
    "rule_set": "function",
    "at_rule": "import",   # @import and @mixin
}

# Map language tag → node-type dict
_LANG_NODE_MAP: dict[str, dict[str, str]] = {
    "python": _PYTHON_NODES,
    "javascript": _JAVASCRIPT_NODES,
    "jsx": _JAVASCRIPT_NODES,
    "typescript": _TYPESCRIPT_NODES,
    "tsx": _TYPESCRIPT_NODES,
    "java": _JAVA_NODES,
    "c": _C_NODES,
    "cpp": _CPP_NODES,
    "csharp": _CSHARP_NODES,
    "go": _GO_NODES,
    "rust": _RUST_NODES,
    "ruby": _RUBY_NODES,
    "php": _PHP_NODES,
    "swift": _SWIFT_NODES,
    "kotlin": _KOTLIN_NODES,
    "scala": _SCALA_NODES,
    "haskell": _HASKELL_NODES,
    "lua": _LUA_NODES,
    "r": _R_NODES,
    "bash": _BASH_NODES,
    "css": _CSS_NODES,
}


# ---------------------------------------------------------------------------
# Generic tree-sitter symbol extractor
# ---------------------------------------------------------------------------


def _name_from_node(node: Any, source: bytes) -> str:
    """Extract a human-readable name from a tree-sitter node.

    Tries common name-bearing child field names; falls back to
    the first identifier child, then to the node type.
    """
    for field in ("name", "identifier", "declarator"):
        child = node.child_by_field_name(field)
        if child is not None:
            return source[child.start_byte: child.end_byte].decode("utf-8", errors="replace")
    # Walk immediate children for first identifier
    for child in node.children:
        if child.type == "identifier":
            return source[child.start_byte: child.end_byte].decode("utf-8", errors="replace")
    return node.type


def _extract_ts_symbols(
    tree: Any,
    source: bytes,
    path: str,
    node_map: dict[str, str],
    lines: list[str],
) -> list[Symbol]:
    """Walk *tree* and collect symbols matching *node_map*.

    Uses a depth-first cursor walk to avoid Python recursion limits.
    """
    symbols: list[Symbol] = []
    visited: set[int] = set()
    stack: list[Any] = [tree.root_node]

    while stack:
        node = stack.pop()
        node_id = node.id
        if node_id in visited:
            continue
        visited.add(node_id)

        sym_type = node_map.get(node.type)
        if sym_type is not None:
            name = _name_from_node(node, source)
            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            content = source[node.start_byte: node.end_byte].decode("utf-8", errors="replace")
            symbols.append(
                Symbol(
                    path=path,
                    symbol_name=name,
                    symbol_type=sym_type,
                    line_start=start_line,
                    line_end=end_line,
                    content=content,
                )
            )

        # Push children in reverse so we process them left-to-right
        stack.extend(reversed(node.children))

    return symbols


# ---------------------------------------------------------------------------
# Language-specific non-tree-sitter extractors
# ---------------------------------------------------------------------------


def _parse_markdown(lines: list[str], path: str) -> list[Symbol]:
    """Extract heading-delimited sections from a Markdown file."""
    symbols: list[Symbol] = []
    heading_re = re.compile(r"^(#{1,6})\s+(.*)")

    sections: list[tuple[str, int]] = []  # (heading_text, line_index)
    for i, line in enumerate(lines):
        m = heading_re.match(line)
        if m:
            sections.append((m.group(2).strip(), i))

    if not sections:
        return _fallback_chunks(lines, path, chunk_size=50)

    for idx, (heading, start_idx) in enumerate(sections):
        end_idx = sections[idx + 1][1] if idx + 1 < len(sections) else len(lines)
        content = "".join(lines[start_idx:end_idx])
        symbols.append(
            Symbol(
                path=path,
                symbol_name=heading,
                symbol_type="function",
                line_start=start_idx + 1,
                line_end=end_idx,
                content=content,
            )
        )
    return symbols


def _parse_yaml(lines: list[str], path: str) -> list[Symbol]:
    """Chunk a YAML file by 30 lines, using top-level keys as names."""
    chunk_size = 30
    symbols: list[Symbol] = []
    top_key_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*):")

    total = len(lines)
    for start in range(0, max(total, 1), chunk_size):
        end = min(start + chunk_size, total)
        chunk_lines = lines[start:end]
        content = "".join(chunk_lines)
        # Use first top-level key found in the chunk as name
        name = f"chunk_{start + 1}"
        for line in chunk_lines:
            m = top_key_re.match(line)
            if m:
                name = m.group(1)
                break
        symbols.append(
            Symbol(
                path=path,
                symbol_name=name,
                symbol_type="chunk",
                line_start=start + 1,
                line_end=end,
                content=content,
            )
        )
    return symbols


def _parse_toml(lines: list[str], path: str) -> list[Symbol]:
    """Extract TOML table headers and key-value pairs."""
    symbols: list[Symbol] = []
    table_re = re.compile(r"^\[([^\]]+)\]")
    kv_re = re.compile(r"^([A-Za-z_][A-Za-z0-9_\-]*)\s*=")

    for i, line in enumerate(lines):
        m_table = table_re.match(line.strip())
        if m_table:
            symbols.append(
                Symbol(
                    path=path,
                    symbol_name=m_table.group(1),
                    symbol_type="function",
                    line_start=i + 1,
                    line_end=i + 1,
                    content=line,
                )
            )
            continue
        m_kv = kv_re.match(line.strip())
        if m_kv:
            symbols.append(
                Symbol(
                    path=path,
                    symbol_name=m_kv.group(1),
                    symbol_type="variable",
                    line_start=i + 1,
                    line_end=i + 1,
                    content=line,
                )
            )
    return symbols if symbols else _fallback_chunks(lines, path, chunk_size=50)


def _parse_sql(lines: list[str], path: str) -> list[Symbol]:
    """Extract CREATE statements and chunk remaining SQL blocks."""
    symbols: list[Symbol] = []
    create_re = re.compile(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|FUNCTION|PROCEDURE|INDEX)\s+(\S+)",
        re.IGNORECASE,
    )
    select_re = re.compile(r"^(SELECT|INSERT|UPDATE|DELETE|WITH)\b", re.IGNORECASE)

    i = 0
    total = len(lines)
    while i < total:
        line = lines[i]
        m = create_re.search(line)
        if m:
            obj_name = m.group(1).rstrip("(").strip()
            raw = line.upper().split()
            if "TABLE" in raw or "VIEW" in raw:
                sym_type = "class"
            elif "FUNCTION" in raw or "PROCEDURE" in raw:
                sym_type = "function"
            else:
                sym_type = "variable"
            # Collect until semicolon
            start = i
            block: list[str] = []
            while i < total:
                block.append(lines[i])
                if ";" in lines[i]:
                    break
                i += 1
            symbols.append(
                Symbol(
                    path=path,
                    symbol_name=obj_name,
                    symbol_type=sym_type,
                    line_start=start + 1,
                    line_end=i + 1,
                    content="".join(block),
                )
            )
        elif select_re.match(line.strip()):
            start = i
            block = []
            while i < total:
                block.append(lines[i])
                if ";" in lines[i]:
                    break
                i += 1
            symbols.append(
                Symbol(
                    path=path,
                    symbol_name=f"chunk_{start + 1}",
                    symbol_type="chunk",
                    line_start=start + 1,
                    line_end=i + 1,
                    content="".join(block),
                )
            )
        i += 1

    return symbols if symbols else _fallback_chunks(lines, path, chunk_size=50)


def _parse_dockerfile(lines: list[str], path: str) -> list[Symbol]:
    """Chunk a Dockerfile by instruction (FROM, RUN, COPY, etc.)."""
    instruction_re = re.compile(
        r"^(FROM|RUN|COPY|ADD|ENV|EXPOSE|WORKDIR|CMD|ENTRYPOINT|LABEL|ARG|VOLUME|USER|ONBUILD|HEALTHCHECK|SHELL)\b",
        re.IGNORECASE,
    )
    symbols: list[Symbol] = []
    block_start = 0
    block_lines: list[str] = []
    block_name = "chunk_1"

    for i, line in enumerate(lines):
        m = instruction_re.match(line.strip())
        if m:
            if block_lines:
                symbols.append(
                    Symbol(
                        path=path,
                        symbol_name=block_name,
                        symbol_type="chunk",
                        line_start=block_start + 1,
                        line_end=i,
                        content="".join(block_lines),
                    )
                )
            block_start = i
            block_lines = [line]
            block_name = m.group(1).upper()
        else:
            block_lines.append(line)

    if block_lines:
        symbols.append(
            Symbol(
                path=path,
                symbol_name=block_name,
                symbol_type="chunk",
                line_start=block_start + 1,
                line_end=len(lines),
                content="".join(block_lines),
            )
        )
    return symbols if symbols else _fallback_chunks(lines, path, chunk_size=50)


def _parse_html(lines: list[str], path: str) -> list[Symbol]:
    """Chunk HTML by <script>/<style> tags; remainder as single chunk."""
    total = len(lines)
    if total <= 100:
        return [
            Symbol(
                path=path,
                symbol_name="document",
                symbol_type="chunk",
                line_start=1,
                line_end=total,
                content="".join(lines),
            )
        ]
    return _fallback_chunks(lines, path, chunk_size=50)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_symbols(path: Path, rel_path: str, language: str) -> list[Symbol]:
    """Extract symbols from *path* for the given *language*.

    For tree-sitter supported languages the file is parsed with the
    appropriate grammar and relevant node types are collected.  If the
    grammar is unavailable, or if *language* has no tree-sitter support,
    the file is chunked using the fallback or a language-specific
    text-based extractor.

    This function never raises — all errors are logged and the fallback
    chunker is used instead.

    Args:
        path: Absolute path to the source file.
        rel_path: POSIX-relative path (used as the ``path`` field in
            returned symbols).
        language: Language tag returned by
            :func:`navcode.indexer.detect_language`.

    Returns:
        List of :class:`Symbol` objects (may be empty for empty files).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read {} for parsing: {}", rel_path, exc)
        return []

    lines = text.splitlines(keepends=True)

    # ------------------------------------------------------------------
    # Languages handled with dedicated text-based extractors
    # ------------------------------------------------------------------
    if language == "markdown":
        return _parse_markdown(lines, rel_path)
    if language == "yaml":
        return _parse_yaml(lines, rel_path)
    if language == "toml":
        return _parse_toml(lines, rel_path)
    if language == "sql":
        return _parse_sql(lines, rel_path)
    if language == "dockerfile":
        return _parse_dockerfile(lines, rel_path)
    if language == "html":
        return _parse_html(lines, rel_path)

    # JSON / XML / text / config / regex → pure chunk (no AST)
    chunk_sizes = {
        "json": 30,
        "xml": 40,
        "text": 20,
        "config": 20,
        "regex": 50,
        "unknown": 50,
    }
    if language in chunk_sizes:
        return _fallback_chunks(lines, rel_path, chunk_size=chunk_sizes[language])

    # ------------------------------------------------------------------
    # tree-sitter path
    # ------------------------------------------------------------------
    node_map = _LANG_NODE_MAP.get(language)
    if node_map is None:
        # Language tag has no node map yet — use fallback
        logger.debug("No node map for language '{}'; using fallback chunks", language)
        return _fallback_chunks(lines, rel_path)

    source = text.encode("utf-8")
    tree = _parse_tree(source, language)

    if tree is None:
        # Grammar unavailable or parse error — fallback
        logger.debug("tree-sitter parse failed for '{}'; using fallback chunks", rel_path)
        return _fallback_chunks(lines, rel_path)

    try:
        symbols = _extract_ts_symbols(tree, source, rel_path, node_map, lines)
    except Exception as exc:
        logger.warning("Symbol extraction error for '{}': {}", rel_path, exc)
        symbols = []

    # If AST walk produced nothing, fall back to chunking
    if not symbols:
        return _fallback_chunks(lines, rel_path)

    return symbols
