# navcode — Project Scaffold Plan

## Overview

Bootstrap the `navcode` Python CLI package from an empty workspace.
This scaffold establishes the git branching model, package layout, core entry points
(`__init__.py`, `_bootstrap.py`, `cli.py`), all stub source files, project metadata
(`pyproject.toml`, `README.md`, `.gitignore`), and cuts the first commit on
`feature/scaffold`.

No business logic is implemented in this plan — only the skeleton that future
feature branches will fill in.

---

## Sub-Task 1 — Git Repository Initialisation

**Intent**
Set up the three-tier branch strategy (`main → dev → feature/scaffold`) so all
subsequent work is tracked correctly from the very first commit.

**Expected Outcomes**
- `git init` run in workspace root.
- Branch `dev` exists, branched off `main`.
- Active branch is `feature/scaffold`, branched off `dev`.

**Todo List**
1. Run `git init` in the workspace root.
2. Run `git checkout -b dev`.
3. Run `git checkout -b feature/scaffold`.

**Relevant Context**
- Project rule: never commit directly to `main` or `dev`.

**Status** `[ ] pending`

---

## Sub-Task 2 — `pyproject.toml`

**Intent**
Define package identity, dependencies, and build system so the package is
installable with `pip install -e .` and the `navcode` console script is wired up.

**Expected Outcomes**
- `pyproject.toml` present in workspace root with all specified fields.
- `[project.scripts]` section maps `navcode` → `navcode.cli:app`.
- `[build-system]` uses `setuptools` legacy backend.

**Todo List**
1. Create `pyproject.toml` with the exact content specified in the brief.

**Relevant Context**
- Entry point: `navcode.cli:app` (Typer app defined in Sub-Task 5).
- Dependencies: `typer`, `rich`, `loguru`, `watchdog`, `httpx`, `numpy`,
  `onnxruntime`, `tree-sitter`, `fastmcp`, `SQLAlchemy`.

**Status** `[ ] pending`

---

## Sub-Task 3 — Package Directory & Stub Files

**Intent**
Create every file in the specified package layout so imports resolve and the
structure is immediately navigable. All stubs share a three-line header comment.

**Expected Outcomes**
- Directory `navcode/` exists with all 11 top-level `.py` files.
- Directory `navcode/adapters/` exists with all 10 adapter stubs.
- Directory `navcode/templates/` exists with all 6 `.md` template stubs.
- Each `.py` stub contains only the three-line header (no logic yet).
- Each `.md` template stub contains only a `# <name>` heading placeholder.

**Todo List**
1. Create `navcode/__init__.py` — leave as stub (content added in Sub-Task 4).
2. Create stubs for: `_bootstrap.py`, `watcher.py`, `indexer.py`, `parser.py`,
   `embeddings.py`, `graph.py`, `classifier.py`, `retriever.py`, `mcp_server.py`.
3. Create `navcode/adapters/__init__.py` and stubs for all 9 adapter modules:
   `base.py`, `claude.py`, `cursor.py`, `codex.py`, `copilot.py`, `bob.py`,
   `kimi.py`, `antigravity.py`, `windsurf.py`, `continue_.py`.
4. Create `navcode/templates/` and 6 markdown stubs:
   `claude.md`, `cursor.md`, `codex.md`, `copilot.md`, `bob.md`, `agents.md`.

**Relevant Context**
- Header comment pattern:
  ```
  # navcode/<filename>.py
  # Nythris Studio — navcode
  # Author: Noman Rafique
  ```

**Status** `[ ] pending`

---

## Sub-Task 4 — `navcode/__init__.py`

**Intent**
Wire the package entry point so that importing `navcode` immediately exposes
`__version__` and triggers the model bootstrap check.

**Expected Outcomes**
- `__version__ = "0.1.0"` exported.
- `ensure_model()` called on import.

**Todo List**
1. Write `navcode/__init__.py` with the two-line body specified in the brief.

**Relevant Context**
- `ensure_model` is defined in `navcode._bootstrap` (Sub-Task 5).
- Call order: `from navcode._bootstrap import ensure_model` must come before
  `ensure_model()`.

**Status** `[ ] pending`

---

## Sub-Task 5 — `navcode/_bootstrap.py`

**Intent**
Implement `ensure_model()` so the ONNX embedding model is downloaded exactly
once (on first use) and cached at `~/.navcode/models/model_quantized.onnx`.
Subsequent imports are a no-op.

**Expected Outcomes**
- `ensure_model()` is a public, typed, documented function.
- Model directory `~/.navcode/models/` is created if absent.
- If `model_quantized.onnx` already exists, the function returns immediately.
- First-run: streams the file from HuggingFace via `httpx`, showing a
  `rich.progress.Progress` bar with download size and speed.
- Network errors are caught and rendered with `rich.console.Console` error
  styling; the exception is re-raised so the caller can decide to abort.
- `loguru` logs key lifecycle events (checking, downloading, saved).

**Todo List**
1. Import `Path` from `pathlib`, `httpx`, `loguru.logger`, `rich.progress.*`,
   `rich.console.Console`.
2. Define `MODEL_URL` and `MODEL_PATH` as module-level constants.
3. Implement `ensure_model() -> None` with:
   - Early-return guard if file exists.
   - `httpx.stream("GET", MODEL_URL, follow_redirects=True)` inside a
     `with` block.
   - `rich.progress.Progress` with `DownloadColumn`, `TransferSpeedColumn`,
     `TimeRemainingColumn`.
   - Write chunks to file, advance progress bar.
   - Catch `httpx.HTTPError` and display via `Console().print` with `[red]`.

**Relevant Context**
- Download URL: `https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model_quantized.onnx`
- Cache path: `Path.home() / ".navcode" / "models" / "model_quantized.onnx"`
- Rule: no `print()` — use `loguru` + `rich` only.

**Status** `[ ] pending`

---

## Sub-Task 6 — `navcode/cli.py` Skeleton

**Intent**
Stand up the Typer application with all five top-level commands so `navcode --help`
is functional immediately, even though command bodies are stubs.

**Expected Outcomes**
- `app = typer.Typer(...)` with a helpful name and help string.
- Five commands registered: `init`, `status`, `reindex`, `logs`, `stats`.
- Each command has a docstring and prints a `[yellow]coming soon[/yellow]`
  panel via `rich`.
- `--version` / `-V` flag prints `navcode 0.1.0` and exits.

**Todo List**
1. Import `typer`, `rich.console.Console`, `rich.panel.Panel`, and
   `navcode.__version__`.
2. Create `app = typer.Typer(name="navcode", ...)`.
3. Add `version_callback` function and attach it to a `--version` option on
   the Typer app via `typer.Option` callback pattern.
4. Implement five `@app.command()` stubs: `init`, `status`, `reindex`,
   `logs`, `stats`.
5. Guard with `if __name__ == "__main__": app()`.

**Relevant Context**
- Typer version callback pattern: define a function that receives
  `value: bool`, check `if value`, print version, raise `typer.Exit()`.
- Rich console: `Console().print(Panel("coming soon", title="[cmd]"))`.

**Status** `[ ] pending`

---

## Sub-Task 7 — `README.md`

**Intent**
Provide the minimal public-facing documentation required for PyPI and GitHub.

**Expected Outcomes**
- `README.md` present at workspace root with all sections from the brief.

**Todo List**
1. Create `README.md` with the exact content specified in the brief.

**Status** `[ ] pending`

---

## Sub-Task 8 — `.gitignore`

**Intent**
Prevent build artifacts, caches, virtual environments, and the `.codenav/`
runtime directory from being tracked.

**Expected Outcomes**
- `.gitignore` present at workspace root with all entries from the brief.

**Todo List**
1. Create `.gitignore` with the entries from the brief.

**Status** `[ ] pending`

---

## Sub-Task 9 — First Commit

**Intent**
Record the entire scaffold as a single atomic commit on `feature/scaffold`
using the mandated conventional-commit format.

**Expected Outcomes**
- `git add .` stages all new files.
- Commit message: `feat(scaffold): initialize navcode project structure and pyproject.toml`
- `git log --oneline` shows exactly one commit on `feature/scaffold`.

**Todo List**
1. Run `git add .`
2. Run `git commit -m "feat(scaffold): initialize navcode project structure and pyproject.toml"`

**Status** `[ ] pending`

---

## File Manifest

| Path | Type | Sub-Task |
|------|------|----------|
| `pyproject.toml` | config | 2 |
| `README.md` | doc | 7 |
| `.gitignore` | config | 8 |
| `navcode/__init__.py` | source | 4 |
| `navcode/_bootstrap.py` | source | 5 |
| `navcode/cli.py` | source | 6 |
| `navcode/watcher.py` | stub | 3 |
| `navcode/indexer.py` | stub | 3 |
| `navcode/parser.py` | stub | 3 |
| `navcode/embeddings.py` | stub | 3 |
| `navcode/graph.py` | stub | 3 |
| `navcode/classifier.py` | stub | 3 |
| `navcode/retriever.py` | stub | 3 |
| `navcode/mcp_server.py` | stub | 3 |
| `navcode/adapters/__init__.py` | stub | 3 |
| `navcode/adapters/base.py` | stub | 3 |
| `navcode/adapters/claude.py` | stub | 3 |
| `navcode/adapters/cursor.py` | stub | 3 |
| `navcode/adapters/codex.py` | stub | 3 |
| `navcode/adapters/copilot.py` | stub | 3 |
| `navcode/adapters/bob.py` | stub | 3 |
| `navcode/adapters/kimi.py` | stub | 3 |
| `navcode/adapters/antigravity.py` | stub | 3 |
| `navcode/adapters/windsurf.py` | stub | 3 |
| `navcode/adapters/continue_.py` | stub | 3 |
| `navcode/templates/claude.md` | template | 3 |
| `navcode/templates/cursor.md` | template | 3 |
| `navcode/templates/codex.md` | template | 3 |
| `navcode/templates/copilot.md` | template | 3 |
| `navcode/templates/bob.md` | template | 3 |
| `navcode/templates/agents.md` | template | 3 |
