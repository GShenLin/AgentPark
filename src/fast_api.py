import argparse
import logging
import os
import sys
from copy import deepcopy

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from src.server_pid_file import install_server_pid_file
from src.web_backend import create_app
from src.windows_parent_monitor import start_env_parent_exit_monitor
from src.windows_parent_monitor import start_frozen_parent_exit_monitor
from src.workspace_settings import find_available_server_port, get_workspace_root, read_server_settings


class Ignore200OKFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if isinstance(args, tuple) and args:
                status = args[-1]
                if isinstance(status, int) and status == 200:
                    return False
        except Exception:
            return True
        return True


def _build_uvicorn_log_config() -> dict:
    cfg = deepcopy(LOGGING_CONFIG)
    cfg.setdefault("filters", {})
    cfg["filters"]["ignore_200_ok"] = {"()": Ignore200OKFilter}

    access_logger = cfg.get("loggers", {}).get("uvicorn.access")
    if isinstance(access_logger, dict):
        filters = access_logger.get("filters")
        if not isinstance(filters, list):
            filters = []
        if "ignore_200_ok" not in filters:
            filters.append("ignore_200_ok")
        access_logger["filters"] = filters

    return cfg


def _run_server(app, *, host: str, port: int, log_config: dict) -> None:
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        reload=False,
        workers=1,
        log_config=log_config,
    )
    server = uvicorn.Server(config)

    def _request_exit() -> None:
        server.should_exit = True

    start_frozen_parent_exit_monitor(exit_func=_request_exit)
    start_env_parent_exit_monitor(exit_func=_request_exit)
    server.run()


def main(argv=None):
    argv = list(argv or [])
    if argv and argv[0] in {"doctor", "capabilities", "config", "chat"}:
        from src.cli import main as cli_main

        raise SystemExit(cli_main(argv))

    server_settings = read_server_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default=server_settings["host"])
    parser.add_argument("--port", type=int, default=server_settings["port"])
    parser.add_argument("--workspace-root", type=str, default="")
    parser.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.workspace_root:
        expected_root = os.path.abspath(get_workspace_root())
        provided_root = os.path.abspath(args.workspace_root)
        if os.path.normcase(provided_root) != os.path.normcase(expected_root):
            raise ValueError(f"--workspace-root must match the resolved workspace root: {expected_root}")
    actual_port = find_available_server_port(args.host, args.port)
    if actual_port != int(args.port):
        print(f"[server] preferred port {args.port} unavailable, using {actual_port}")
    os.environ["AITOOLS_SERVER_HOST"] = str(args.host)
    os.environ["AITOOLS_SERVER_PORT"] = str(actual_port)
    pid_path = install_server_pid_file(args.host, actual_port)
    print(f"[server] pid file: {pid_path}")
    _run_server(
        create_app(),
        host=args.host,
        port=actual_port,
        log_config=_build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    main(sys.argv[1:])

