from __future__ import annotations

from typing import Any, Callable

from src.cli_commands.companion_config_selection import (
    capability_choices,
    provider_choices,
    reasoning_choices,
    toggle_companion_capability,
    update_companion_config,
    update_companion_provider,
)


RunChoiceMenu = Callable[..., str | None]
PrintError = Callable[[str], None]


def select_provider(target: Any, run_menu: RunChoiceMenu, print_error: PrintError) -> bool:
    choices = provider_choices(str(target.config.get("mode") or "chat"))
    if not choices:
        print_error("no configured provider supports the current mode")
        return False
    selected = run_menu(
        title="Select Provider",
        text="Use Up/Down to select a provider, then press Enter.",
        choices=choices,
        default=str(target.config.get("provider_id") or ""),
    )
    if selected is None:
        return False
    update_companion_provider(target, selected)
    return True


def select_reasoning(target: Any, run_menu: RunChoiceMenu, print_error: PrintError) -> bool:
    provider_id = str(target.config.get("provider_id") or "").strip()
    choices = reasoning_choices(provider_id)
    if not choices:
        print_error(f"provider does not support selectable reasoning effort: {provider_id}")
        return False
    selected = run_menu(
        title="Select Reasoning Effort",
        text="Use Up/Down to select reasoning effort, then press Enter.",
        choices=choices,
        default=str(target.config.get("reasoning_effort") or ""),
    )
    if selected is None:
        return False
    update_companion_config(target, "reasoning_effort", selected)
    return True


def toggle_capability(
    target: Any,
    kind: str,
    run_menu: RunChoiceMenu,
    print_error: PrintError,
) -> bool:
    choices, selected_values = capability_choices(target, kind)
    if not choices:
        print_error(f"no {kind} capability is available")
        return False
    selected = run_menu(
        title=f"Toggle {kind.upper() if kind == 'mcp' else kind.title()}",
        text="Use Up/Down to select an item. Enter enables or removes it and exits.",
        choices=choices,
        default=next((value for value, _label in choices if value in selected_values), choices[0][0]),
        checked=selected_values,
    )
    if selected is None:
        return False
    toggle_companion_capability(target, kind, selected)
    return True


__all__ = ["select_provider", "select_reasoning", "toggle_capability"]
