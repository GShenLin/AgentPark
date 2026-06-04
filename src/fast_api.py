import argparse
import logging
import os
import sys
import threading
import time
import webbrowser
from copy import deepcopy

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from src.windows_parent_monitor import start_frozen_parent_exit_monitor
from src.workspace_settings import find_available_server_port, read_server_settings, resolve_local_client_host


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


def main(argv=None):
    start_frozen_parent_exit_monitor()
    server = read_server_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default=server["host"])
    parser.add_argument("--port", type=int, default=server["port"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    actual_port = find_available_server_port(args.host, args.port)
    if actual_port != int(args.port):
        print(f"[server] preferred port {args.port} unavailable, using {actual_port}")
    os.environ["AITOOLS_SERVER_HOST"] = str(args.host)
    os.environ["AITOOLS_SERVER_PORT"] = str(actual_port)
    browser_host = resolve_local_client_host(args.host)

    def _open_browser():
        time.sleep(5)
        try:
            webbrowser.open(f"http://{browser_host}:{actual_port}/", new=1)
        except Exception:
            pass

    if not args.no_browser:
        threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run(
        "src.web_backend:app",
        host=args.host,
        port=actual_port,
        reload=False,
        workers=1,
        log_config=_build_uvicorn_log_config(),
    )


if __name__ == "__main__":
    main(sys.argv[1:])

