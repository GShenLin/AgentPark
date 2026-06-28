from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from typing import Any

from src.cli_commands.capabilities import list_capabilities, mutate_capability
from src.cli_commands.chat import run_chat
from src.cli_commands.config import diff_config, validate_config
from src.cli_commands.doctor import run_doctor


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        payload = args.handler(args)
        _print_payload(payload, json_output=bool(getattr(args, "json", False)))
        if payload.get("status") == "success":
            return int(payload.get("_exit_code") or 0)
        return 1
    except Exception as exc:
        payload = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "exception_type": type(exc).__name__}
        _print_payload(payload, json_output=bool(getattr(args, "json", False)))
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subcommands = parser.add_subparsers(dest="command", required=True)

    doctor = subcommands.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=run_doctor)

    chat = subcommands.add_parser("chat")
    chat.add_argument("--config", default="", help="Companion config path. Defaults to memories/companion/config.json.")
    chat.add_argument("--message", default="", help="Run one prompt and exit. Omit for interactive chat.")
    chat.add_argument("--json", action="store_true", help="Machine-readable output for --message mode.")
    chat.add_argument("--plain", action="store_true", help=argparse.SUPPRESS)
    chat.add_argument(
        "--backend",
        choices=["auto", "prompt", "msvcrt", "win32", "plain"],
        default="",
        help=argparse.SUPPRESS,
    )
    chat.add_argument("--debug-terminal", action="store_true", help="Print terminal/input diagnostics before starting chat.")
    chat.set_defaults(handler=run_chat)

    capabilities = subcommands.add_parser("capabilities")
    capability_subcommands = capabilities.add_subparsers(dest="capability_action", required=True)
    cap_list = capability_subcommands.add_parser("list")
    _add_node_args(cap_list)
    cap_list.add_argument("--refresh", action="store_true", help="Invalidate discovery caches before listing.")
    cap_list.add_argument("--json", action="store_true")
    cap_list.set_defaults(handler=list_capabilities)
    for action in ("enable", "disable"):
        command = capability_subcommands.add_parser(action)
        _add_node_args(command)
        command.add_argument("--kind", required=True, choices=["tool", "mcp", "skill", "plugin"])
        command.add_argument("--name", action="append", required=True)
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=mutate_capability)

    config = subcommands.add_parser("config")
    config_subcommands = config.add_subparsers(dest="config_action", required=True)
    validate = config_subcommands.add_parser("validate")
    _add_node_args(validate)
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=validate_config)
    diff = config_subcommands.add_parser("diff")
    _add_node_args(diff)
    diff.add_argument("--fields", required=True)
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(handler=diff_config)
    return parser


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    _restore_windows_console_input_echo()


def _restore_windows_console_input_echo() -> None:
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        stdin_handle = kernel32.GetStdHandle(-10)
        if stdin_handle in (0, -1):
            return
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(stdin_handle, ctypes.byref(mode)):
            return
        enable_processed_input = 0x0001
        enable_line_input = 0x0002
        enable_echo_input = 0x0004
        next_mode = mode.value | enable_processed_input | enable_line_input | enable_echo_input
        kernel32.SetConsoleMode(stdin_handle, next_mode)
    except Exception:
        return


def _add_node_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--node", required=True)
    parser.add_argument("--graph", default="default")


def _print_payload(payload: dict[str, Any], *, json_output: bool) -> None:
    if payload.get("_printed"):
        return
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if payload.get("status") == "error":
        print(payload.get("error") or payload.get("detail") or "error")
        return
    if "checks" in payload:
        for check in payload.get("checks") or []:
            print(f"[{check.get('status')}] {check.get('name')}: {check.get('detail')}")
        return
    if "capabilities" in payload:
        for kind, group in (payload.get("capabilities") or {}).items():
            print(f"{kind}:")
            for item in group.get("descriptors") or []:
                marker = "*" if item.get("enabled") else "-"
                print(f"  {marker} {item.get('id')} [{item.get('status')}] {item.get('label')}")
        return
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
