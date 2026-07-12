import os
from datetime import datetime
import json


class BaseMemory:
    def __init__(self, provider_name, memory_file_path=None):
        self.provider_name = provider_name
        self.current_memory_name = provider_name
        self.current_memory_path = self._resolve_memory_path(memory_file_path or provider_name)
        self.memory_content = self._load_memory()

    def createMemory(self, memory_name):
        self.current_memory_name = memory_name
        self.current_memory_path = self._resolve_memory_path(memory_name)
        self.memory_content = self._load_memory()
        print(f"Switched to memory: {memory_name}")

    def readMemory(self, memory_name):
        return self._load_memory(memory_name)

    def getMemoryPath(self):
        return self.current_memory_path

    def Log(self, line, raw=False):
        try:
            text = "" if line is None else str(line)
            memory_path = self.current_memory_path
            if not memory_path:
                return ""
            memory_dir = os.path.dirname(memory_path)
            if not memory_dir:
                memory_dir = os.path.dirname(os.path.abspath(memory_path))
            if not memory_dir:
                memory_dir = os.getcwd()
            os.makedirs(memory_dir, exist_ok=True)
            log_path = os.path.join(memory_dir, "log.txt")
            if raw:
                entry = text if text.endswith("\n") else f"{text}\n"
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                entry = f"[{timestamp}] {text}\n"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry)
            return entry
        except Exception:
            return ""

    def on_message(self, role_or_message, content=None):
        if isinstance(role_or_message, dict):
            message = role_or_message
            role = message.get("role")
        else:
            role = role_or_message
            message = {"role": role_or_message, "content": content}

        if role not in ["user", "assistant", "tool", "function", "system"]:
            return ""

        content_to_write = self._format_memory_entry(message)
        if not content_to_write:
            return ""

        info_type = message.get("type") if isinstance(message, dict) else None
        info_key = str(info_type or "").strip().lower()
        parts = message.get("parts")
        has_function_call = bool(message.get("tool_calls")) or bool(message.get("function_call")) or info_key in {"function_call", "tool_call"}
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and part.get("functionCall"):
                    has_function_call = True
                    break
        write_memory = not has_function_call
        if role == "tool":
            write_memory = False
        appended = self._append_memory(role, content_to_write, write_memory=write_memory)
        if appended:
            self.memory_content = (self.memory_content or "") + appended
        return appended

    def build_messages_with_memory(self, messages):
        return [
            msg.copy()
            for msg in messages
            if isinstance(msg, dict)
            and str(msg.get("role") or "").strip().lower() != "assistant_progress"
            and str(msg.get("context_policy") or "").strip().lower() != "exclude"
        ]

    def read_tail_lines(self, max_lines=100, max_bytes=200000):
        try:
            max_lines = int(max_lines)
        except Exception:
            max_lines = 100
        try:
            max_bytes = int(max_bytes)
        except Exception:
            max_bytes = 200000

        if max_lines <= 0:
            return ""
        if max_bytes <= 0:
            max_bytes = 200000

        path = self.current_memory_path
        if not path or not os.path.exists(path):
            return ""

        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                read_size = min(size, max_bytes)
                f.seek(-read_size, os.SEEK_END)
                data = f.read(read_size)
        except Exception:
            return ""

        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            try:
                text = data.decode(errors="replace")
            except Exception:
                return ""

        lines = text.splitlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines).strip()

    def _load_memory(self, memory_name=None):
        if memory_name is None:
            memory_path = self.current_memory_path
        else:
            memory_path = self._resolve_memory_path(memory_name)

        if os.path.exists(memory_path):
            with open(memory_path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _get_default_memory_dir(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "memories")

    def _resolve_memory_path(self, memory_name_or_path):
        if memory_name_or_path is None:
            memory_name_or_path = self.provider_name

        if not isinstance(memory_name_or_path, str):
            memory_name_or_path = str(memory_name_or_path)

        looks_like_path = os.path.isabs(memory_name_or_path) or (os.sep in memory_name_or_path) or ("/" in memory_name_or_path) or memory_name_or_path.lower().endswith(".md")
        if looks_like_path:
            memory_path = memory_name_or_path
            if not memory_path.lower().endswith(".md"):
                memory_path = memory_path + ".md"
            memory_dir = os.path.dirname(memory_path)
            if memory_dir:
                os.makedirs(memory_dir, exist_ok=True)
            return memory_path

        memory_dir = self._get_default_memory_dir()
        os.makedirs(memory_dir, exist_ok=True)
        return os.path.join(memory_dir, f"{memory_name_or_path}.md")

    def _append_memory(self, role, content, write_memory=True):
        try:
            if content is None:
                return ""
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            appended = f"\n**[{timestamp}] {role}**: {content}\n"
            memory_dir = os.path.dirname(self.current_memory_path)
            if memory_dir:
                os.makedirs(memory_dir, exist_ok=True)
            if write_memory:
                with open(self.current_memory_path, "a", encoding="utf-8") as f:
                    f.write(appended)
            self.Log(appended, raw=True)
            return appended
        except Exception as e:
            print(f"Warning: Failed to write to memory file: {e}")
            return ""

    def _format_memory_entry(self, message):
        role = message.get("role")
        content = message.get("content")

        if role in ["user", "assistant"]:
            summary = self._summarize_tool_calls(message)
            if content is None or content == "":
                return summary
            if role == "assistant" and isinstance(content, str):
                text = content.strip()
                if text.startswith("{") and text.endswith("}"):
                    try:
                        payload = json.loads(text)
                    except Exception:
                        payload = None
                    if isinstance(payload, dict) and payload.get("event") == "leader_decision":
                        decision = payload.get("decision")
                        if isinstance(decision, dict) and decision.get("status") == "done":
                            final = decision.get("final")
                            if isinstance(final, str) and final.strip():
                                final_text = final.strip()
                                if summary:
                                    return "\n\n" + final_text + "\n\n" + summary
                                return "\n\n" + final_text
            if summary:
                return f"{content}\n{summary}"
            return content

        if role in ["tool", "function"]:
            name = message.get("name")
            return self._summarize_tool_result(name, content)

        return None

    def _summarize_tool_calls(self, message):
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            items = []
            for call in tool_calls:
                func = call.get("function") if isinstance(call, dict) else None
                if not isinstance(func, dict):
                    continue
                name = func.get("name")
                args = func.get("arguments")
                details = self._extract_tool_details(name, args)
                items.append(details)
            if items:
                return "Tool calls:\n" + "\n".join(items)

        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            name = function_call.get("name")
            args = function_call.get("args")
            details = self._extract_tool_details(name, args)
            if details:
                return "Tool calls:\n" + details

        parts = message.get("parts")
        if isinstance(parts, list):
            items = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                fc = part.get("functionCall")
                if not isinstance(fc, dict):
                    continue
                name = fc.get("name")
                args = fc.get("args")
                details = self._extract_tool_details(name, args)
                items.append(details)
            if items:
                return "Tool calls:\n" + "\n".join(items)

        return ""

    def _extract_tool_details(self, name, args):
        if not isinstance(name, str) or not name.strip():
            return ""
        args_obj = args
        if isinstance(args, str):
            try:
                args_obj = json.loads(args)
            except Exception:
                args_obj = args

        if name == "execute_console_command":
            command = ""
            if isinstance(args_obj, dict):
                command = str(args_obj.get("command") or "")
            if command:
                return f"- {name}: {command}"
            return f"- {name}"

        if name == "read_file":
            if isinstance(args_obj, dict):
                file_path = args_obj.get("file_path")
                start_line = args_obj.get("start_line")
                end_line = args_obj.get("end_line")
                parts = []
                if file_path:
                    parts.append(str(file_path))
                if start_line is not None or end_line is not None:
                    parts.append(f"lines={start_line}-{end_line}")
                suffix = " ".join(parts).strip()
                return f"- {name}: {suffix}" if suffix else f"- {name}"
            return f"- {name}"

        try:
            serialized = json.dumps(args_obj, ensure_ascii=False)
        except Exception:
            serialized = str(args_obj)
        if serialized and serialized != "null":
            return f"- {name}: {serialized}"
        return f"- {name}"

    def _summarize_tool_result(self, name, content):
        tool_name = name if isinstance(name, str) and name.strip() else "tool"
        if content is None:
            return f"{tool_name}: (no content)"

        payload = content
        if isinstance(content, str):
            try:
                payload = json.loads(content)
            except Exception:
                payload = content

        if isinstance(payload, dict):
            if tool_name == "execute_console_command":
                command = payload.get("command")
                status = payload.get("status")
                returncode = payload.get("returncode")
                parts = []
                if command:
                    parts.append(str(command))
                if status is not None:
                    parts.append(f"status={status}")
                if returncode is not None:
                    parts.append(f"code={returncode}")
                suffix = " ".join(parts).strip()
                return f"{tool_name}: {suffix}" if suffix else tool_name

            if tool_name == "execute_curl_command":
                url = payload.get("url")
                status = payload.get("status")
                returncode = payload.get("returncode")
                stdout = payload.get("stdout")
                parts = []
                if url:
                    parts.append(str(url))
                if status is not None:
                    parts.append(f"status={status}")
                if returncode is not None:
                    parts.append(f"code={returncode}")
                if isinstance(stdout, str) and stdout.strip():
                    preview = stdout.strip()
                    if len(preview) > 300:
                        preview = preview[:300] + "...(truncated)"
                    parts.append(f"stdout={json.dumps(preview, ensure_ascii=False)}")
                suffix = " ".join(parts).strip()
                return f"{tool_name}: {suffix}" if suffix else tool_name

            if tool_name == "read_file":
                file_path = payload.get("file_path")
                read_lines = payload.get("read_lines")
                status = payload.get("status")
                parts = []
                if file_path:
                    parts.append(str(file_path))
                if read_lines:
                    parts.append(f"lines={read_lines}")
                if status:
                    parts.append(f"status={status}")
                suffix = " ".join(parts).strip()
                return f"{tool_name}: {suffix}" if suffix else tool_name

            if payload.get("action") == "inspect_image" and payload.get("image_path"):
                return f"{tool_name}: image_path={payload.get('image_path')}"

            short = {}
            for k in ("status", "file_path", "image_path", "action", "error"):
                if k in payload:
                    short[k] = payload.get(k)
            if short:
                return f"{tool_name}: {json.dumps(short, ensure_ascii=False)}"

        text = str(payload)
        text = text.strip()
        if not text:
            return f"{tool_name}: (empty)"
        limit = 500
        if len(text) > limit:
            text = text[:limit] + "...(truncated)"
        return f"{tool_name}: {text}"
