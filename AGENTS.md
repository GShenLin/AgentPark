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

## File Size Policy

- When a single file exceeds 400 lines, evaluate a split plan immediately.
- Split by responsibility first: interfaces, implementations, orchestration flow, and shared utilities.
