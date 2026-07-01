## Core Principles

- Prioritize clear architecture and long-term extensibility over delivery speed.
- Prefer meaningful abstraction and explicit boundaries; avoid thin wrapper layers.
- Do not preserve backward-compatibility paths for legacy logic unless explicitly required.
- use utf-8 format

## Implementation Constraints

- Do not introduce heuristic shortcuts for quick fallback behavior.
- Do not relax type and protocol contracts just to accept unstructured returns.
- Do not hide real issues through swallowed errors, silent degradation, or default-value masking.

## Change Strategy

- When legacy design is flawed, fix the primary path directly instead of stacking patches.
- Define module boundaries and data contracts before implementing new capabilities.
- Keep changes localized, verifiable, and maintainable; avoid boundaryless sprawl.

## Workspace Operations

- The primary shell environment is Windows. Do not use Bash-only command syntax such as heredocs (`python - <<'PY'`) with the default console; use `python -c`, a temporary script, or an explicit PowerShell-compatible form.
- When passing multiple PowerShell paths that may contain spaces, build an explicit quoted array before calling commands such as `Get-ChildItem -Path`.
- For very large or deeply nested JSON catalogs, prefer a quiet structured parser such as `node -e` with `JSON.parse` over PowerShell `ConvertFrom-Json`, which can fail noisily and dump large input to stderr.
- Before running `git pull --rebase`, commit intended changes or stash work that should not be committed yet. Do not start a rebase from an unstaged working tree.

## File Size Policy

- When a single file exceeds 400 lines, evaluate a split plan immediately.
- Split by responsibility first: interfaces, implementations, orchestration flow, and shared utilities.
