from __future__ import annotations

import os
import threading
import time
import uuid

from src.channels.errors import ChannelConfigError
from src.channels.receiver_models import ReceiverConfigRef, ReceiverKey, ReceiverRuntimeConfig, RoutedEnvelope
from src.channels.receiver_routing import envelope_receiver_command, normalize_receiver_name, route_receiver_envelope
from src.channels.weixin import WeixinChannelDriver
from src.channels.weixin.storage import CHANNEL_ID, resolve_account_id
from src.message_protocol import envelope_preview
from src.value_parsing import parse_optional_int_value
from src.web_backend import runtime_paths, state_store


class ChannelService:
    def __init__(self, core: object) -> None:
        self.core = core
        self._driver = WeixinChannelDriver()
        self._lock = threading.Lock()
        self._receivers: dict[str, dict] = {}
        self._account_pollers: dict[str, dict] = {}

    def list_channels(self) -> dict:
        return {
            "channels": [
                {
                    "id": CHANNEL_ID,
                    "label": "OpenClaw Weixin",
                    "accounts": self._driver.list_accounts(),
                    "supports": ["login_qr", "long_poll", "receive_image", "send_text", "send_image"],
                }
            ]
        }

    def list_receivers(self) -> dict:
        with self._lock:
            receivers = [
                {
                    "key": key,
                    "graph_id": info.get("graph_id"),
                    "node_id": info.get("node_id"),
                    "channel": info.get("channel"),
                    "account_id": info.get("account_id"),
                    "receiver_name": info.get("receiver_name") or "",
                    "running": self._thread_alive(info),
                    "last_error": info.get("last_error"),
                    "last_message_at": info.get("last_message_at"),
                }
                for key, info in sorted(self._receivers.items())
            ]
        return {"receivers": receivers}

    def start_autostart_receivers(self) -> dict:
        started = 0
        for graph_id, node_id, cfg in self._iter_receiver_configs():
            if bool(cfg.get("AutoStart")):
                self.start_receiver(graph_id, node_id, cfg)
                started += 1
        return {"started": started}

    def stop_all(self) -> None:
        with self._lock:
            infos = list(self._account_pollers.values())
        for info in infos:
            stop_event = info.get("stop_event")
            if isinstance(stop_event, threading.Event):
                stop_event.set()

    def control_receiver(self, graph_id: str, node_id: str, payload: dict | None = None) -> dict:
        action = str((payload or {}).get("action") or "").strip().lower()
        if action == "start":
            return self.start_receiver(graph_id, node_id)
        if action == "stop":
            return self.stop_receiver(graph_id, node_id)
        if action == "status" or not action:
            return self.receiver_status(graph_id, node_id)
        raise ChannelConfigError(f"unsupported receiver action: {action}")

    def login_start(self, graph_id: str, node_id: str, payload: dict | None = None) -> dict:
        cfg = self._read_receiver_config(graph_id, node_id)
        self._assert_weixin(cfg)
        account_id = str((payload or {}).get("account_id") or cfg.get("AccountId") or "").strip()
        return self._driver.start_login(account_id=account_id, force=bool((payload or {}).get("force")))

    def login_wait(self, graph_id: str, node_id: str, payload: dict | None = None) -> dict:
        self._assert_weixin(self._read_receiver_config(graph_id, node_id))
        session_key = str((payload or {}).get("session_key") or "").strip()
        timeout_seconds = int((payload or {}).get("timeout_seconds") or 60)
        return self._driver.wait_login(session_key=session_key, timeout_seconds=timeout_seconds)

    def start_receiver(self, graph_id: str, node_id: str, cfg: dict | None = None) -> dict:
        safe_graph_id, safe_node_id = self._resolve_existing_receiver(graph_id, node_id)
        receiver_cfg = cfg if isinstance(cfg, dict) else self._read_receiver_config(safe_graph_id, safe_node_id)
        runtime_cfg = self._parse_receiver_runtime_config(receiver_cfg)

        key = ReceiverKey(safe_graph_id, safe_node_id).text()
        with self._lock:
            existing = self._receivers.get(key)
            if existing and self._thread_alive(existing):
                return {"ok": True, "running": True, "key": key}
            poller = self._account_pollers.get(runtime_cfg.account_id)
            if poller and self._thread_alive(poller):
                info = self._receiver_info(
                    safe_graph_id,
                    safe_node_id,
                    runtime_cfg,
                    poller.get("stop_event"),
                    poller.get("thread"),
                )
                self._receivers[key] = info
                self._set_receiver_state(safe_graph_id, safe_node_id, "idle", f"Receiver running: {CHANNEL_ID}")
                return {"ok": True, "running": True, "key": key, "account_id": runtime_cfg.account_id}
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._receiver_loop,
                args=(safe_graph_id, safe_node_id, stop_event),
                daemon=True,
                name=f"channel-receiver-{safe_graph_id}-{safe_node_id}",
            )
            info = self._receiver_info(safe_graph_id, safe_node_id, runtime_cfg, stop_event, thread)
            self._receivers[key] = info
            self._account_pollers[runtime_cfg.account_id] = {
                "account_id": runtime_cfg.account_id,
                "owner_key": key,
                "stop_event": stop_event,
                "thread": thread,
            }
            thread.start()
        self._set_receiver_state(safe_graph_id, safe_node_id, "idle", f"Receiver running: {CHANNEL_ID}")
        return {"ok": True, "running": True, "key": key, "account_id": runtime_cfg.account_id}

    def stop_receiver(self, graph_id: str, node_id: str) -> dict:
        safe_graph_id, safe_node_id = self._sanitize_pair(graph_id, node_id)
        key = ReceiverKey(safe_graph_id, safe_node_id).text()
        with self._lock:
            info = self._receivers.pop(key, None)
            account_id = str((info or {}).get("account_id") or "").strip()
            if account_id and not self._has_other_account_receivers(account_id, key):
                poller = self._account_pollers.pop(account_id, None)
                stop_event = (poller or {}).get("stop_event")
                if isinstance(stop_event, threading.Event):
                    stop_event.set()
        self._set_receiver_state(safe_graph_id, safe_node_id, "idle", "Receiver stopped.")
        return {"ok": True, "running": False, "key": key}

    def receiver_status(self, graph_id: str, node_id: str) -> dict:
        safe_graph_id, safe_node_id = self._sanitize_pair(graph_id, node_id)
        key = ReceiverKey(safe_graph_id, safe_node_id).text()
        with self._lock:
            info = dict(self._receivers.get(key) or {})
        runtime_cfg = self._read_receiver_runtime_config(safe_graph_id, safe_node_id)
        return {
            "ok": True,
            "key": key,
            "running": self._thread_alive(info),
            "channel": info.get("channel") or CHANNEL_ID,
            "account_id": runtime_cfg.account_id,
            "receiver_name": runtime_cfg.receiver_name,
            "last_error": info.get("last_error") or "",
            "last_message_at": info.get("last_message_at") or "",
        }

    def _receiver_loop(
        self,
        graph_id: str,
        node_id: str,
        stop_event: threading.Event,
    ) -> None:
        key = ReceiverKey(graph_id, node_id).text()
        while not stop_event.is_set():
            try:
                poll_cfg = self._read_receiver_runtime_config(graph_id, node_id)
                self._update_receiver_runtime_info(key, poll_cfg)
                updates = self._driver.get_updates(
                    account_id=poll_cfg.account_id,
                    timeout_seconds=poll_cfg.poll_timeout_seconds,
                )
                messages = updates.get("msgs")
                if not isinstance(messages, list):
                    messages = []
                for message in messages:
                    if stop_event.is_set():
                        break
                    if not isinstance(message, dict):
                        continue
                    message_cfg = self._read_receiver_runtime_config(graph_id, node_id)
                    self._update_receiver_runtime_info(key, message_cfg)
                    envelope = self._driver.message_to_envelope(account_id=poll_cfg.account_id, message=message)
                    routed_items = self._route_receiver_envelopes(graph_id, node_id, envelope, message_cfg)
                    trace_id = uuid.uuid4().hex
                    for routed in routed_items:
                        routed_envelope = routed.envelope
                        if routed.command_matched:
                            self._set_receiver_state(routed.graph_id, routed.node_id, "idle", "Receiver active.")
                        if routed_envelope is None:
                            continue
                        self.core.graph_api.emit_graph(
                            routed.graph_id,
                            {"from_id": routed.node_id, "payload": routed_envelope, "trace_id": trace_id},
                        )
                        self._set_receiver_state(routed.graph_id, routed.node_id, "idle", envelope_preview(routed_envelope))
                    with self._lock:
                        info = self._receivers.get(key)
                        if info is not None:
                            info["last_message_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                            info["last_error"] = ""
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    info = self._receivers.get(key)
                    if info is not None:
                        info["last_error"] = message
                self._set_receiver_state(graph_id, node_id, "idle", f"Receiver error: {message}")
                stop_event.wait(5)
        self._set_receiver_state(graph_id, node_id, "idle", "Receiver stopped.")

    @staticmethod
    def _receiver_info(
        graph_id: str,
        node_id: str,
        runtime_cfg: ReceiverRuntimeConfig,
        stop_event: threading.Event | None,
        thread: threading.Thread | None,
    ) -> dict:
        return {
            "graph_id": graph_id,
            "node_id": node_id,
            "channel": CHANNEL_ID,
            "account_id": runtime_cfg.account_id,
            "receiver_name": runtime_cfg.receiver_name,
            "stop_event": stop_event,
            "thread": thread,
            "last_error": "",
            "last_message_at": "",
        }

    def _has_other_account_receivers(self, account_id: str, excluded_key: str) -> bool:
        for key, info in self._receivers.items():
            if key == excluded_key:
                continue
            if str((info or {}).get("account_id") or "").strip() == account_id:
                return True
        return False

    def _update_receiver_runtime_info(self, key: str, runtime_cfg: ReceiverRuntimeConfig) -> None:
        with self._lock:
            info = self._receivers.get(key)
            if info is not None:
                info["account_id"] = runtime_cfg.account_id
                info["receiver_name"] = runtime_cfg.receiver_name
                info["active"] = runtime_cfg.active

    def _iter_receiver_configs(self):
        graphs_dir = runtime_paths._get_graphs_dir()
        if not os.path.isdir(graphs_dir):
            return
        for graph_id in os.listdir(graphs_dir):
            graph_dir = os.path.join(graphs_dir, graph_id)
            if not os.path.isdir(graph_dir):
                continue
            for node_id in os.listdir(graph_dir):
                cfg_path = os.path.join(graph_dir, node_id, "config.json")
                if not os.path.exists(cfg_path):
                    continue
                cfg = state_store._read_json_dict(cfg_path)
                if isinstance(cfg, dict) and str(cfg.get("type_id") or "").strip() == "channel_receiver_node":
                    yield self.core.graph_runtime._sanitize_graph_id(graph_id), self.core.graph_runtime._sanitize_node_id(node_id), cfg

    def _read_receiver_config(self, graph_id: str, node_id: str) -> dict:
        safe_graph_id, safe_node_id = self._resolve_existing_receiver(graph_id, node_id)
        cfg_path = self.core.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        cfg = state_store._read_json_dict(cfg_path)
        if not isinstance(cfg, dict) or not cfg:
            raise ChannelConfigError("receiver node config does not exist")
        if str(cfg.get("type_id") or "").strip() != "channel_receiver_node":
            raise ChannelConfigError("node is not a ChannelReceiver")
        return cfg

    def _read_receiver_runtime_config(self, graph_id: str, node_id: str) -> ReceiverRuntimeConfig:
        return self._parse_receiver_runtime_config(self._read_receiver_config(graph_id, node_id))

    def _parse_receiver_runtime_config(self, cfg: dict) -> ReceiverRuntimeConfig:
        self._assert_weixin(cfg)
        try:
            poll_timeout_seconds = parse_optional_int_value(
                "PollTimeoutSeconds",
                cfg.get("PollTimeoutSeconds"),
                minimum=1,
                maximum=60,
            )
        except ValueError as exc:
            raise ChannelConfigError(str(exc)) from exc

        return ReceiverRuntimeConfig(
            account_id=resolve_account_id(cfg.get("AccountId")),
            receiver_name=str(cfg.get("Name") or "").strip(),
            active=bool(cfg.get("Active")),
            poll_timeout_seconds=poll_timeout_seconds if poll_timeout_seconds is not None else 35,
        )

    def _resolve_existing_receiver(self, graph_id: str, node_id: str) -> tuple[str, str]:
        safe_graph_id, safe_node_id = self._sanitize_pair(graph_id, node_id)
        cfg_path = self.core.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not cfg_path or not os.path.exists(cfg_path):
            raise ChannelConfigError("receiver node config does not exist")
        return safe_graph_id, safe_node_id

    def _sanitize_pair(self, graph_id: str, node_id: str) -> tuple[str, str]:
        safe_graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.core.graph_runtime._sanitize_node_id(node_id)
        if not safe_node_id:
            raise ChannelConfigError("node_id is required")
        return safe_graph_id, safe_node_id

    def _set_receiver_state(self, graph_id: str, node_id: str, state: str, last_message: str) -> None:
        cfg_path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        if not cfg_path:
            return
        _ = state
        state_store._set_node_config_last_message(cfg_path, str(last_message or ""))

    def _set_receiver_active(self, graph_id: str, node_id: str, active: bool) -> None:
        cfg_path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        if not cfg_path:
            return
        cfg = state_store._read_json_dict(cfg_path)
        if not isinstance(cfg, dict) or not cfg:
            return
        cfg["Active"] = bool(active)
        state_store._write_json_dict(cfg_path, cfg)

    def _find_receiver_by_name(
        self,
        graph_id: str,
        receiver_name: str,
        account_id: str,
    ) -> ReceiverConfigRef | None:
        target_name = normalize_receiver_name(receiver_name)
        target_account_id = resolve_account_id(account_id)
        if not target_name:
            return None
        _ = graph_id
        for candidate_graph_id, candidate_node_id, cfg in self._iter_receiver_configs_for_scope():
            candidate_name = normalize_receiver_name(cfg.get("Name"))
            if candidate_name != target_name:
                continue
            if resolve_account_id(cfg.get("AccountId")) != target_account_id:
                continue
            return ReceiverConfigRef(candidate_graph_id, candidate_node_id, cfg)
        return None

    def _activate_receiver_name(self, graph_id: str, active_node_id: str, account_id: str) -> None:
        safe_graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        active_cfg = self._read_receiver_config(safe_graph_id, active_node_id)
        target_name = normalize_receiver_name(active_cfg.get("Name"))
        target_account_id = resolve_account_id(account_id)
        if not target_name:
            return
        for candidate_graph_id, candidate_node_id, cfg in self._iter_receiver_configs_for_scope():
            candidate_name = normalize_receiver_name(cfg.get("Name"))
            if not candidate_name:
                continue
            if resolve_account_id(cfg.get("AccountId")) != target_account_id:
                continue
            should_activate = (
                candidate_graph_id == safe_graph_id
                and candidate_node_id == active_node_id
                and candidate_name == target_name
            )
            self._set_receiver_active(candidate_graph_id, candidate_node_id, should_activate)

    def _iter_receiver_configs_in_graph(self, graph_id: str):
        safe_graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
        for candidate_graph_id, candidate_node_id, cfg in self._iter_receiver_configs_for_scope():
            if candidate_graph_id == safe_graph_id:
                yield candidate_graph_id, candidate_node_id, cfg

    def _iter_receiver_configs_for_scope(self):
        graphs_dir = runtime_paths._get_graphs_dir()
        if not os.path.isdir(graphs_dir):
            return
        for graph_id in os.listdir(graphs_dir):
            graph_dir = os.path.join(graphs_dir, graph_id)
            if not os.path.isdir(graph_dir):
                continue
            safe_graph_id = self.core.graph_runtime._sanitize_graph_id(graph_id)
            for node_id in os.listdir(graph_dir):
                cfg_path = os.path.join(graph_dir, node_id, "config.json")
                if not os.path.exists(cfg_path):
                    continue
                cfg = state_store._read_json_dict(cfg_path)
                if not isinstance(cfg, dict) or str(cfg.get("type_id") or "").strip() != "channel_receiver_node":
                    continue
                yield safe_graph_id, self.core.graph_runtime._sanitize_node_id(node_id), cfg

    @staticmethod
    def _thread_alive(info: dict) -> bool:
        thread = info.get("thread") if isinstance(info, dict) else None
        return isinstance(thread, threading.Thread) and thread.is_alive()

    @staticmethod
    def _assert_weixin(cfg: dict) -> None:
        channel = str(cfg.get("Channel") or CHANNEL_ID).strip()
        if channel != CHANNEL_ID:
            raise ChannelConfigError(f"unsupported channel: {channel}")

    def _route_receiver_envelope(
        self,
        graph_id: str,
        node_id: str,
        envelope: dict,
        runtime_cfg: ReceiverRuntimeConfig,
    ) -> RoutedEnvelope:
        command = envelope_receiver_command(envelope)
        if command is not None:
            if normalize_receiver_name(command[0]) == normalize_receiver_name(runtime_cfg.receiver_name):
                route = route_receiver_envelope(envelope, runtime_cfg.receiver_name, active=True)
                if not route.command_matched:
                    return RoutedEnvelope(envelope=None, graph_id=graph_id, node_id=node_id)
                self._set_receiver_active(graph_id, node_id, True)
                self._activate_receiver_name(graph_id, node_id, runtime_cfg.account_id)
                return RoutedEnvelope(envelope=route.envelope, graph_id=graph_id, node_id=node_id, command_matched=True)

            target = self._find_receiver_by_name(graph_id, command[0], runtime_cfg.account_id)

            if target is None:
                return RoutedEnvelope(envelope=None, graph_id=graph_id, node_id=node_id)
            target_cfg = self._parse_receiver_runtime_config(target.cfg)
            route = route_receiver_envelope(envelope, target_cfg.receiver_name, active=True)
            if not route.command_matched:
                return RoutedEnvelope(envelope=None, graph_id=graph_id, node_id=node_id)
            self._set_receiver_active(target.graph_id, target.node_id, True)
            self._activate_receiver_name(target.graph_id, target.node_id, target_cfg.account_id)
            return RoutedEnvelope(envelope=route.envelope, graph_id=target.graph_id, node_id=target.node_id, command_matched=True)
        route = route_receiver_envelope(envelope, runtime_cfg.receiver_name, runtime_cfg.active)
        return RoutedEnvelope(envelope=route.envelope, graph_id=graph_id, node_id=node_id, command_matched=route.command_matched)

    def _route_receiver_envelopes(
        self,
        graph_id: str,
        node_id: str,
        envelope: dict,
        runtime_cfg: ReceiverRuntimeConfig,
    ) -> list[RoutedEnvelope]:
        if envelope_receiver_command(envelope) is not None:
            return [self._route_receiver_envelope(graph_id, node_id, envelope, runtime_cfg)]

        target_account_id = resolve_account_id(runtime_cfg.account_id)
        routed_items: list[RoutedEnvelope] = []
        for candidate_graph_id, candidate_node_id, cfg in self._iter_receiver_configs_for_scope():
            candidate_cfg = self._parse_receiver_runtime_config(cfg)
            if candidate_cfg.account_id != target_account_id:
                continue
            route = route_receiver_envelope(envelope, candidate_cfg.receiver_name, candidate_cfg.active)
            if route.envelope is None:
                continue
            routed_items.append(
                RoutedEnvelope(
                    envelope=route.envelope,
                    graph_id=candidate_graph_id,
                    node_id=candidate_node_id,
                    command_matched=route.command_matched,
                )
            )
        return routed_items
