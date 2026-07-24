from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .client import RemoteWorkerClient, default_display_name
from .discovery import DiscoveryServer
from .identity import IdentityStore, WorkerConfiguration, default_state_directory
from .operations import StandaloneOperationRegistry, validate_working_path
from .protocol import DISCOVERY_PORT


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    state_directory = Path(arguments.state_directory).expanduser().resolve()
    logger = _configure_logging(state_directory)
    try:
        workspace_path = validate_working_path(arguments.workspace)
        store = IdentityStore(state_directory / "identity.json")
        identity = store.load_or_create()
        configuration = WorkerConfiguration(store, identity)
        if arguments.server:
            configuration.configure_server(arguments.server)

        operations = StandaloneOperationRegistry()
        client = RemoteWorkerClient(
            configuration,
            operations,
            workspace_path=workspace_path,
            display_name=default_display_name(workspace_path),
            logger=logger,
        )
        discovery = DiscoveryServer(
            configuration.configure_server,
            port=arguments.discovery_port,
            logger=logger,
        )
        discovery.start()
        try:
            client.run_forever()
        except KeyboardInterrupt:
            logger.info("AgentPark Remote stopped by user")
        finally:
            client.stop()
            discovery.stop()
        return 0
    except Exception:
        logger.exception("AgentPark Remote terminated because startup failed")
        return 1


def _parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AgentPark standalone Remote workspace worker")
    parser.add_argument("--server", default="", help="AgentPark server origin; normally supplied by browser discovery")
    parser.add_argument("--workspace", default=_default_workspace(), help="Default remote WorkingPath")
    parser.add_argument(
        "--state-directory",
        default=str(default_state_directory()),
        help="Persistent identity and log directory",
    )
    parser.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT)
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
