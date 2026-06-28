import json


class DoubaoToolFeedbackMixin:
    @staticmethod
    def _openai_tool_call_ids(message):
        if not isinstance(message, dict):
            return []
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            return []
        ids = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "").strip()
            if call_id:
                ids.append(call_id)
        return ids

    @staticmethod
    def _tool_result_status_payload(message):
        if not isinstance(message, dict):
            return None
        payload = None
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            try:
                payload = json.loads(content)
            except Exception:
                payload = None
        if not isinstance(payload, dict):
            payload = {}
        status = str(message.get("status") or payload.get("status") or "").strip().lower()
        error = str(message.get("error") or payload.get("error") or "").strip()
        if not status and not error:
            return None
        return payload, status, error

    @classmethod
    def _is_error_tool_result(cls, message):
        status_payload = cls._tool_result_status_payload(message)
        if status_payload is None:
            return False
        _payload, status, error = status_payload
        if error:
            return True
        return bool(status and status not in {"completed", "success", "succeeded", "ok"})

    @classmethod
    def _compact_error_tool_message(cls, message):
        status_payload = cls._tool_result_status_payload(message)
        if status_payload is None:
            return None
        payload, status, error = status_payload
        call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
        if not call_id:
            return None
        tool_name = str(message.get("name") or payload.get("tool") or "tool").strip() or "tool"
        compact = {
            "status": status or "error",
            "tool": tool_name,
        }
        if error:
            compact["error"] = error
        for key in ("url", "returncode", "stderr", "diagnostics"):
            if key in payload:
                compact[key] = payload.get(key)
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": tool_name,
            "content": json.dumps(compact, ensure_ascii=False),
        }

    @classmethod
    def _tool_result_message_for_model(cls, message):
        call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
        if not call_id:
            return None
        if cls._is_error_tool_result(message):
            return cls._compact_error_tool_message(message)
        content = message.get("content")
        if content is None:
            return None
        tool_name = str(message.get("name") or "tool").strip() or "tool"
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": tool_name,
            "content": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
        }

    def _restore_recent_tool_results(self, messages):
        if not isinstance(messages, list):
            return messages
        raw_messages = self.messages if isinstance(getattr(self, "messages", None), list) else []
        assistant_index = -1
        call_ids: set[str] = set()
        for index, message in enumerate(raw_messages):
            if not isinstance(message, dict) or str(message.get("role") or "").strip().lower() != "assistant":
                continue
            ids = self._openai_tool_call_ids(message)
            if ids:
                assistant_index = index
                call_ids = set(ids)
        if assistant_index < 0 or not call_ids:
            return messages

        present_tool_ids = {
            str(message.get("tool_call_id") or message.get("call_id") or "").strip()
            for message in messages
            if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "tool"
        }
        restored = []
        for message in raw_messages[assistant_index + 1 :]:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").strip().lower()
            if role in {"user", "assistant"}:
                break
            if role != "tool":
                continue
            call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
            if call_id not in call_ids or call_id in present_tool_ids:
                continue
            tool_message = self._tool_result_message_for_model(message)
            if tool_message is not None:
                restored.append(tool_message)
                present_tool_ids.add(call_id)
        if not restored:
            return messages

        output = [dict(message) for message in messages]
        insert_at = len(output)
        for index, message in enumerate(output):
            if not isinstance(message, dict) or str(message.get("role") or "").strip().lower() != "assistant":
                continue
            ids = set(self._openai_tool_call_ids(message))
            if ids and ids.intersection(call_ids):
                insert_at = index + 1
        output[insert_at:insert_at] = restored
        return output

    @staticmethod
    def _is_tool_submission_size_error(error_text):
        text = str(error_text or "").strip().lower()
        if not text:
            return False
        if "total tokens of image and text exceed max message tokens" in text:
            return True
        if "context" in text and "token" in text and ("exceed" in text or "maximum" in text):
            return True
        return False

    def _tool_result_submission_max_chars(self):
        config = getattr(self, "config", None)
        if not isinstance(config, dict) or "toolResultSubmissionMaxChars" not in config:
            raise ValueError(
                "provider.toolResultSubmissionMaxChars is required for tool result submission sizing."
            )
        raw = config.get("toolResultSubmissionMaxChars")
        if isinstance(raw, bool):
            raise ValueError("provider.toolResultSubmissionMaxChars must be a positive integer.")
        try:
            value = int(raw)
        except Exception as exc:
            raise ValueError("provider.toolResultSubmissionMaxChars must be a positive integer.") from exc
        if value <= 0:
            raise ValueError("provider.toolResultSubmissionMaxChars must be a positive integer.")
        return value

    @staticmethod
    def _tool_result_submission_error_payload(
        *,
        tool_name,
        call_id,
        provider_error,
        original_result_chars,
    ):
        return {
            "status": "tool_result_submission_error",
            "tool": str(tool_name or "").strip() or "tool",
            "call_id": str(call_id or "").strip(),
            "error": "The tool executed, but its result was too large to submit back to the model.",
            "provider_error": str(provider_error or ""),
            "original_result_chars": int(original_result_chars or 0),
            "instruction": (
                "Use this error as feedback. Do not repeat the same tool call with a larger output limit. "
                "Choose a narrower request, ask for a smaller output, or answer from the available context."
            ),
        }

    def _emit_tool_result_submission_compacted_notice(
        self,
        *,
        tool_name,
        call_id,
        original_result_chars,
        limit,
        provider_error="",
    ):
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if not callable(emitter):
            return
        error_text = str(provider_error or "").strip()
        reason = f" Provider error: {error_text}" if error_text else ""
        emitter(
            message=(
                f"Tool result for {str(tool_name or '').strip() or 'tool'} "
                f"({str(call_id or '').strip()}) was {int(original_result_chars or 0)} chars, "
                f"exceeding provider.toolResultSubmissionMaxChars={int(limit)}; "
                f"submitted tool_result_submission_error instead.{reason}"
            ),
            stage="tool_result_submission_compacted",
        )

    def _compact_tool_result_for_submission_if_needed(
        self,
        *,
        tool_name,
        call_id,
        content,
        provider_error="",
        max_chars=None,
    ):
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        limit = int(max_chars or self._tool_result_submission_max_chars())
        if len(text) <= limit:
            return text
        resolved_provider_error = provider_error or f"Tool result exceeded local submission limit of {limit} characters."
        self._emit_tool_result_submission_compacted_notice(
            tool_name=tool_name,
            call_id=call_id,
            original_result_chars=len(text),
            limit=limit,
            provider_error=resolved_provider_error,
        )
        return json.dumps(
            self._tool_result_submission_error_payload(
                tool_name=tool_name,
                call_id=call_id,
                provider_error=resolved_provider_error,
                original_result_chars=len(text),
            ),
            ensure_ascii=False,
        )

    def _compact_tool_result_message_for_submission(self, message):
        if not isinstance(message, dict):
            return message
        if str(message.get("role") or "").strip().lower() != "tool":
            return message
        call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
        if not call_id or "content" not in message:
            return message
        tool_name = str(message.get("name") or "").strip() or "tool"
        compacted_content = self._compact_tool_result_for_submission_if_needed(
            tool_name=tool_name,
            call_id=call_id,
            content=message.get("content"),
        )
        if compacted_content == message.get("content"):
            return message
        compacted = dict(message)
        compacted["content"] = compacted_content
        return compacted

    def _compact_tool_result_messages_for_submission(self, messages):
        if not isinstance(messages, list):
            return messages
        output = []
        changed = False
        for message in messages:
            compacted = self._compact_tool_result_message_for_submission(message)
            output.append(compacted)
            if compacted is not message:
                changed = True
        return output if changed else messages

    def _replace_recent_tool_result_with_submission_error(self, error_text):
        if not self._is_tool_submission_size_error(error_text):
            return False
        messages = self.messages if isinstance(self.messages, list) else []
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "tool":
                continue
            content = message.get("content")
            try:
                payload = json.loads(content) if isinstance(content, str) and content.strip() else None
            except Exception:
                payload = None
            if isinstance(payload, dict) and payload.get("status") == "tool_result_submission_error":
                return False

            original_chars = len(str(content or ""))
            tool_name = str(message.get("name") or "").strip() or "tool"
            call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
            replacement = self._tool_result_submission_error_payload(
                tool_name=tool_name,
                call_id=call_id,
                provider_error=str(error_text or ""),
                original_result_chars=original_chars,
            )
            message["content"] = json.dumps(replacement, ensure_ascii=False)
            self._emit_tool_result_submission_compacted_notice(
                tool_name=tool_name,
                call_id=call_id,
                original_result_chars=original_chars,
                limit=self._tool_result_submission_max_chars(),
                provider_error=str(error_text or ""),
            )
            return True
        return False
