"""Skill activation lifetime declared in SKILL.md metadata."""
from __future__ import annotations


def read_activation_scope(frontmatter: dict) -> str:
    metadata = frontmatter.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("skill metadata must be a mapping")
    scope = metadata.get("activation_scope", "turn")
    if scope not in ("conversation", "turn"):
        raise ValueError("metadata.activation_scope must be 'conversation' or 'turn'")
    return scope
