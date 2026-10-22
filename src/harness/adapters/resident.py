"""Resident CLI adapter ownership: configuration, provider lease, and native child.

The node process manager serializes lifecycle operations. Conversation files live
outside this object and survive close(), configuration changes and host restarts.
"""
from __future__ import annotations

import os

from src.harness.config import load_cli_request
from src.harness.events import HarnessEvents
from src.harness.execution import execution_session
from src.harness.install_manager import command_argv, install_root
from src.harness.responses_gateway import HarnessResponsesGateway


class ResidentCliAdapter:
    harness_id = ""

    def __init__(self):
        self.client = None
        self.lease = None
        self.signature = None

    def options(self, context):
        return None

    def is_alive(self):
        return self.client is not None and self.client.is_alive()

    def prepare(self, context):
        request = load_cli_request(self.harness_id, context)
        argv = command_argv(self.harness_id)
        options = self.options(context)
        signature = (request.binding, request.cwd, request.state_dir, request.instruction,
                     request.reasoning_effort, request.permission_mode, request.timeout, tuple(argv), options)
        if self.signature != signature or not self.is_alive():
            self.close()
            request.state_dir.mkdir(parents=True, exist_ok=True)
            self.lease = HarnessResponsesGateway.instance().register(request.binding.provider_id,
                model=request.binding.model_id, reasoning_effort=request.reasoning_effort
                if self.harness_id in {"minimax_code", "opencode", "antigravity"} else "")
            env = {**os.environ, "AGENTPARK_HARNESS_TOKEN": self.lease.token}
            if self.harness_id == "minimax_code":
                env.setdefault("NODE_COMPILE_CACHE", str(install_root(self.harness_id) / "compile-cache"))
            try:
                # Subclasses assign the child before their handshake so failed
                # initialization is always closed, with its gateway lease.
                self.open(request, argv, env, options,
                          HarnessEvents(self.harness_id, request.binding.provider_id, None))
                self.signature = signature
            except BaseException:
                self.close()
                raise
        return request

    def run(self, text, context):
        request = self.prepare(context)
        with execution_session(self.harness_id, request.binding.provider_id, request, context) as events:
            self.client.reset(request.timeout, request.cancel_source)
            try:
                return self.turn(text, request, events)
            except BaseException:
                self.close()
                raise

    def close(self):
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.lease is not None:
            HarnessResponsesGateway.instance().release(self.lease.token)
            self.lease = None
        self.signature = None

    def open(self, request, argv, env, options, events):
        raise NotImplementedError

    def turn(self, text, request, events):
        raise NotImplementedError
