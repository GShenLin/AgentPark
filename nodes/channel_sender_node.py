from __future__ import annotations

from nodes.base_node import BaseNode
from src.channels.errors import ChannelConfigError
from src.channels.weixin import WeixinChannelDriver
from src.channels.weixin import storage as weixin_storage
from src.message_protocol import normalize_envelope
from src.value_parsing import parse_optional_int_value


class Node(BaseNode):
    name = "ChannelSender"
    description = "Send upstream node output back through a selected external channel."
    input_capabilities = ["text", "structured", "resource:file", "resource:image"]
    output_capabilities = ["text", "structured"]
    config_defaults = {
        "Channel": "openclaw-weixin",
        "Name": "",
        "AccountId": "",
        "ToUserId": "",
        "TimeoutSeconds": 15,
    }
    config_schema = {
        "Channel": {
            "type": "select",
            "label": "Channel",
            "options": [{"value": "openclaw-weixin", "label": "OpenClaw Weixin"}],
        },
        "AccountId": {
            "type": "text",
            "label": "AccountId",
            "description": "OpenClaw Weixin account used to send this message.",
        },
        "Name": {
            "type": "text",
            "label": "Name",
            "description": "Optional sender name prepended to outgoing text, for example Name:\\nmessage.",
        },
        "ToUserId": {
            "type": "text",
            "label": "ToUserId",
            "description": "OpenClaw Weixin recipient user id.",
        },
        "TimeoutSeconds": {
            "type": "number",
            "label": "TimeoutSeconds",
            "min": 1,
            "max": 120,
            "step": 1,
        },
    }

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        channel = str(ctx.get("Channel") or "openclaw-weixin").strip()
        if channel != "openclaw-weixin":
            raise ChannelConfigError(f"unsupported channel: {channel}")

        envelope = normalize_envelope(message, default_role="assistant")
        default_target = weixin_storage.load_default_target()
        account_id = str(ctx.get("AccountId") or default_target.get("accountId") or "").strip()
        to_user_id = str(ctx.get("ToUserId") or default_target.get("toUserId") or "").strip()
        context_token = self._resolve_context_token(ctx.get("ContextToken"), account_id, to_user_id, default_target)
        try:
            timeout_seconds = parse_optional_int_value(
                "TimeoutSeconds",
                ctx.get("TimeoutSeconds"),
                minimum=1,
                maximum=120,
            )
        except ValueError as exc:
            raise ChannelConfigError(str(exc)) from exc
        if timeout_seconds is None:
            timeout_seconds = 15
        sender_name = str(ctx.get("Name") or "").strip().lstrip("/")
        text = self._apply_sender_name(self._extract_text(envelope).strip(), sender_name)
        image_paths = self._extract_image_paths(envelope)

        if not account_id:
            raise ChannelConfigError("ChannelSender requires a logged-in or recently active Weixin account")
        if not to_user_id:
            raise ChannelConfigError("ChannelSender requires a recipient user id or a recent inbound Weixin message")
        if not text and not image_paths:
            raise ChannelConfigError("ChannelSender requires non-empty text or image resource")

        driver = WeixinChannelDriver()
        sent: list[dict] = []
        if text:
            sent.append(
                driver.send_text(
                    account_id=account_id,
                    to_user_id=to_user_id,
                    text=text,
                    context_token=context_token,
                    timeout_seconds=timeout_seconds,
                )
            )
        for image_path in image_paths:
            sent.append(
                driver.send_image(
                    account_id=account_id,
                    to_user_id=to_user_id,
                    file_path=image_path,
                    context_token=context_token,
                    timeout_seconds=timeout_seconds,
                )
            )
        output = {
            "channel": "openclaw-weixin",
            "message_ids": [item.get("message_id") for item in sent],
            "to": to_user_id,
            "text_sent": bool(text),
            "image_count": len(image_paths),
        }
        return {
            "display": f"Sent to {to_user_id}: {len(sent)} item(s)",
            "routes": [{"output_index": 0, "payload": {"type": "structured", "data": output}}],
        }

    @staticmethod
    def _resolve_context_token(configured: object, account_id: str, to_user_id: str, default_target: dict) -> str:
        configured_text = str(configured or "").strip()
        if configured_text:
            return configured_text
        target_account_id = str(default_target.get("accountId") or "").strip()
        target_user_id = str(default_target.get("toUserId") or "").strip()
        if target_account_id == account_id and target_user_id == to_user_id:
            target_token = str(default_target.get("contextToken") or "").strip()
            if target_token:
                return target_token
        if account_id and to_user_id:
            state_token = weixin_storage.load_context_token(account_id, to_user_id)
            if state_token:
                return state_token
        return ""

    @staticmethod
    def _apply_sender_name(text: str, sender_name: str) -> str:
        body = str(text or "").strip()
        name = str(sender_name or "").strip()
        if not body or not name:
            return body
        return f"{name}:\n{body}"

    @staticmethod
    def _extract_text(envelope: dict) -> str:
        lines: list[str] = []
        for part in envelope.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "").strip().lower() == "text":
                text = str(part.get("text") or "")
                if text.strip():
                    lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _extract_image_paths(envelope: dict) -> list[str]:
        output: list[str] = []
        for part in envelope.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "").strip().lower() != "resource":
                continue
            resource = part.get("resource")
            if not isinstance(resource, dict):
                continue
            if str(resource.get("kind") or "").strip().lower() != "image":
                continue
            uri = str(resource.get("uri") or "").strip()
            if uri and uri not in output:
                output.append(uri)
        return output
