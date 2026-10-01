from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from src.runtime_environment import initialize_runtime_environment

from .client import default_display_name
from .identity import default_state_directory
from .launcher import RemoteSettings, WorkerLauncher, load_settings, show_settings


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    state_directory = Path(arguments.state_directory).expanduser().resolve()
    logger = _configure_logging(state_directory)
    try:
        initialize_runtime_environment()
        defaults = RemoteSettings(display_name=default_display_name(arguments.workspace), workspace=arguments.workspace)
        settings = load_settings(state_directory / "settings.json", defaults)
        updates = {}
        if arguments.server:
            updates["server_address"] = arguments.server
        if arguments.workspace != _default_workspace():
            updates["workspace"] = arguments.workspace
        settings = settings.model_copy(update=updates)
        launcher = WorkerLauncher(state_directory, logger)
        try:
            if arguments.headless:
                launcher.start(settings)
                launcher.thread.join()
                if launcher.status.startswith("连接失败"):
                    return 1
            else:
                show_settings(launcher, settings)
        except KeyboardInterrupt:
            logger.info("AgentPark Remote stopped by user")
        finally:
            launcher.stop()
            if launcher.thread:
                launcher.thread.join(timeout=40)
        return 0
    except Exception:
        logger.exception("AgentPark Remote terminated because startup failed")
        return 1


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentPark standalone Remote workspace worker")
    parser.add_argument("--server", default="", help="Target server IP/address: probe AgentPark first, then its authentication center")
    parser.add_argument("--workspace", default=_default_workspace(), help="Default remote WorkingPath")
    parser.add_argument(
        "--state-directory",
        default=str(default_state_directory()),
        help="Persistent identity and log directory",
    )
    parser.add_argument("--headless", action="store_true", help="Run using saved settings without opening the settings window")
    return parser.parse_args(argv)


def _default_workspace() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.getcwd()


def _configure_logging(state_directory: Path) -> logging.Logger:
    state_directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("agentpark.remote")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            state_directory / "AgentParkRemote.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
        logger.addHandler(handler)
    return logger


if __name__ == "__main__":
    raise SystemExit(main())
