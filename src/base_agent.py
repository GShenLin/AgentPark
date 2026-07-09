from abc import ABC, abstractmethod
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
import json
import os
import time
from src.base_agent_manager import BaseAgentManager
from src.config_loader import ConfigLoader
from src.base_memory import BaseMemory
from src.providers.provider_request_summary import build_provider_request_summary
from src.providers.provider_request_summary import next_provider_request_index
from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE
from src.providers.provider_runtime_events import emit_provider_runtime_notice
from src.tool.base_tool import BaseTool
from src.tool_failure_memory_notice import ToolFailureMemoryNoticeMixin
from src.tool_context_compaction_gate import ToolContextCompactionGateMixin


class BaseAgent(ToolContextCompactionGateMixin, ToolFailureMemoryNoticeMixin, ABC):
    def __init__(self, provider_name, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        self.provider_name = provider_name
        self._config = {}
        self.messages = []
        self.tool_failure_memory_notice_enabled = False
        self._tool_context_compaction_since_last = 0
        self.internal_memory_enabled = bool(internal_memory_enabled)
        self.memory = BaseMemory(provider_name, memory_file_path=memory_file_path)
        self.tools = BaseTool(self)
        self.manager = BaseAgentManager(self)
        if isinstance(system_prompt, str) and system_prompt.strip():
            self.Message("system", system_prompt.strip())
        if self.internal_memory_enabled:
            tail = self.memory.read_tail_lines(100)
            if isinstance(tail, str) and tail.strip():
                self.Message("system", f"[Memory Tail]\n{tail.strip()}", persist=False)

    @property
    def config(self):
        cfg = getattr(self, "_config", None)
        return cfg if isinstance(cfg, dict) else {}

    @config.setter
    def config(self, value):
        self._config = value if isinstance(value, dict) else {}

    @property
    def current_memory_name(self):
        return self.memory.current_memory_name

    @current_memory_name.setter
    def current_memory_name(self, value):
        self.memory.current_memory_name = value

    @property
    def current_memory_path(self):
        return self.memory.current_memory_path

    @current_memory_path.setter
    def current_memory_path(self, value):
        self.memory.current_memory_path = value

    @property
    def memory_content(self):
        return self.memory.memory_content

    @memory_content.setter
    def memory_content(self, value):
        self.memory.memory_content = value

    @property
    def tool_declarations(self):
        return self.tools.tool_declarations

    @tool_declarations.setter
    def tool_declarations(self, value):
        self.tools.tool_declarations = value

    @property
    def function_map(self):
        return self.tools.function_map

    @function_map.setter
    def function_map(self, value):
        self.tools.function_map = value

    @property
    def preflight_enabled(self):
        return self.tools.preflight_enabled

    @preflight_enabled.setter
    def preflight_enabled(self, value):
        self.tools.preflight_enabled = value

    def addTool(self, tool_name):
        return self.tools.addTool(tool_name)

    def createMemory(self, memory_name):
        return self.memory.createMemory(memory_name)

    def readMemory(self, memory_name):
        return self.memory.readMemory(memory_name)

    def getMemoryPath(self):
        return self.memory.getMemoryPath()

    def send(self, *args, **kwargs):
        return self.Send(*args, **kwargs)

    def passWork(self, agent, task):
        return self.manager.passWork(agent, task)

    def finishWork(self):
        return self.manager.finishWork()

    def Message(self, role, content, persist=True, **kwargs):
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.messages.append(msg)
        if persist:
            self._persist_assistant_tool_call_note(msg)
        if persist and self.internal_memory_enabled:
            self.memory.on_message(msg)

    def _persist_assistant_tool_call_note(self, message):
        if not self._is_visible_assistant_tool_call_note(message):
            return
        callback = getattr(self, "_agentpark_persist_assistant_tool_call_note", None)
        if callable(callback):
            callback(message)

    @staticmethod
    def _is_visible_assistant_tool_call_note(message):
        if not isinstance(message, dict):
            return False
        if str(message.get("role") or "").strip().lower() != "assistant":
            return False
        if not isinstance(message.get("tool_calls"), list) or not message.get("tool_calls"):
            return False
        content = message.get("content")
        if isinstance(content, str):
            return bool(content.strip())
        if not isinstance(content, list):
            return False
        for part in content:
            if not isinstance(part, dict):
                continue
            if str(part.get("text") or "").strip():
                return True
        return False

    def Log(self, line):
        self.memory.Log(line)

    def _append_memory(self, role, content, write_memory=True):
        if not self.internal_memory_enabled:
            return ""
        return self.memory._append_memory(role, content, write_memory=write_memory)

    def execute_tool(self, name, args):
        return self.tools.execute_tool(name, args)

    def run_task(self, task, use_preflight=None):
        return self.tools.run_task(task, use_preflight=use_preflight)

    def process_tool_result(self, tool_result):
        return self.tools.process_tool_result(tool_result)

    def makePlan(self, user_task, ):
        return self.manager.makePlan(user_task )

    @abstractmethod
    def Send(self):
        pass

    def _get_messages_with_memory(self):
        current_messages = self.memory.build_messages_with_memory(self.messages)
        if not self.internal_memory_enabled:
            return current_messages

        system_messages = []
        last_user_index = -1
        for i, msg in enumerate(current_messages):
            if msg.get("role") == "system":
                system_messages.append(msg)
            if msg.get("role") == "user":
                last_user_index = i

        if last_user_index == -1:
            non_system = [m for m in current_messages if m.get("role") != "system"]
            return system_messages + non_system

        tail = [m for m in current_messages[last_user_index:] if m.get("role") != "system"]
        return system_messages + tail

    def _read_provider_config_from_file(self):
        provider_name = str(getattr(self, "provider_name", "") or "").strip()
        if not provider_name:
            return self.config

        return ConfigLoader().get_provider_config(provider_name)

    def _get_provider_config(self):
        return self.config

    def _emit_provider_request_summary(
        self,
        summary: dict | None = None,
        *,
        current_input=None,
        tools_payload=None,
        stream=False,
        request_api="",
        responses_mode="",
        requested_responses_mode="",
        context_update=None,
        instructions="",
        tool_choice="",
        parallel_tool_calls=None,
        include=None,
    ) -> dict:
        payload = summary if isinstance(summary, dict) else build_provider_request_summary(
            request_index=next_provider_request_index(self),
            current_input=current_input,
            tools_payload=tools_payload,
            stream=bool(stream),
            request_api=request_api,
            responses_mode=responses_mode,
            requested_responses_mode=requested_responses_mode,
            context_update=context_update,
            instructions=instructions,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            include=include,
        )
        emit_provider_runtime_notice(
            getattr(self, "tool_event_callback", None),
            provider=getattr(self, "provider_name", "provider"),
            message=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            stage=PROVIDER_REQUEST_SUMMARY_STAGE,
        )
        return payload

    def _emit_provider_payload_request_summary(
        self,
        payload: dict,
        *,
        request_api: str,
        stream: bool | None = None,
    ) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("provider request summary payload must be an object.")
        effective_stream = bool(payload.get("stream")) if stream is None else bool(stream)
        current_input = payload.get("input") if "input" in payload else payload.get("messages")
        system_text = str(payload.get("system") or "").strip()
        if system_text and isinstance(current_input, list):
            current_input = [{"role": "system", "content": system_text}] + current_input
        return self._emit_provider_request_summary(
            current_input=current_input,
            tools_payload=payload.get("tools"),
            stream=effective_stream,
            request_api=request_api,
            instructions=str(payload.get("instructions") or payload.get("system") or ""),
            tool_choice=str(payload.get("tool_choice") or ""),
            parallel_tool_calls=payload.get("parallel_tool_calls"),
            include=payload.get("include"),
        )

    def _resolve_parallel_workers(self, task_count):
        if not isinstance(task_count, int) or task_count <= 0:
            return 1
        config = self._get_provider_config()
        configured = config.get("maxParallelToolCalls", task_count)
        try:
            configured = int(configured)
        except Exception:
            configured = task_count
        if configured <= 0:
            configured = task_count
        return max(1, min(task_count, configured))

    def _resolve_tool_worker_timeout_sec(self):
        config = self._get_provider_config()
        sec_value = config.get("toolWorkerTimeoutSec")
        if sec_value is not None:
            try:
                sec_value = float(sec_value)
                return sec_value if sec_value > 0 else 20.0
            except Exception:
                return 20.0

        ms_value = config.get("toolWorkerTimeoutMs")
        if ms_value is not None:
            try:
                ms_value = float(ms_value)
                return (ms_value / 1000.0) if ms_value > 0 else 20.0
            except Exception:
                return 20.0

        return 20.0

    def _execute_tasks_parallel_ordered(
        self,
        tasks,
        run_task,
        build_error_result=None,
        build_timeout_result=None,
        task_to_meta=None,
    ):
        if not isinstance(tasks, list) or not tasks:
            return []

        def _get_task_meta(task):
            if callable(task_to_meta):
                try:
                    name, call_id = task_to_meta(task)
                    return name, call_id
                except Exception:
                    return None, None
            return None, None

        def _default_error_result(task, error, _index):
            tool_name, call_id = _get_task_meta(task)
            return self._build_tool_execution_result(
                status="error",
                tool_name=tool_name,
                call_id=call_id,
                error=str(error),
            )

        def _default_timeout_result(task, timeout_seconds, _index):
            tool_name, call_id = _get_task_meta(task)
            return self._build_tool_execution_result(
                status="timeout",
                tool_name=tool_name,
                call_id=call_id,
                error=f"Tool worker exceeded {timeout_seconds:.2f}s.",
            )

        error_builder = build_error_result if callable(build_error_result) else _default_error_result
        timeout_builder = build_timeout_result if callable(build_timeout_result) else _default_timeout_result

        max_workers = self._resolve_parallel_workers(len(tasks))
        if max_workers <= 1 or len(tasks) == 1:
            ordered = []
            for index, task in enumerate(tasks):
                try:
                    ordered.append(run_task(task))
                except Exception as e:
                    ordered.append(error_builder(task, e, index))
            return ordered

        ordered_results = [None] * len(tasks)
        worker_timeout = self._resolve_tool_worker_timeout_sec()
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_index = {
                executor.submit(run_task, task): index
                for index, task in enumerate(tasks)
            }
            pending = set(future_to_index.keys())
            deadline = time.monotonic() + worker_timeout

            while pending:
                remain = deadline - time.monotonic()
                if remain <= 0:
                    break

                done, pending = wait(pending, timeout=remain, return_when=FIRST_COMPLETED)
                if not done:
                    break

                for future in done:
                    index = future_to_index[future]
                    try:
                        ordered_results[index] = future.result()
                    except Exception as e:
                        ordered_results[index] = error_builder(tasks[index], e, index)

            for future in pending:
                index = future_to_index[future]
                future.cancel()
                ordered_results[index] = timeout_builder(tasks[index], worker_timeout, index)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        for index, result in enumerate(ordered_results):
            if result is None:
                ordered_results[index] = error_builder(
                    tasks[index],
                    RuntimeError("Tool worker returned no result."),
                    index,
                )
        return ordered_results

    def _build_tool_execution_result(self, status, tool_name=None, call_id=None, error=None):
        payload = {"status": status}
        if isinstance(tool_name, str) and tool_name:
            payload["tool"] = tool_name
        if isinstance(error, str) and error:
            payload["error"] = error

        result = {
            "func_name": tool_name,
            "cleaned_result": json.dumps(payload, ensure_ascii=False),
            "image_data": None,
        }
        if call_id is not None:
            result["call_id"] = call_id
        return result

    def _build_non_retryable_tool_warning(self, tool_name, cleaned_result):
        if not isinstance(cleaned_result, str):
            return None
        try:
            payload = json.loads(cleaned_result)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None

        status = str(payload.get("status") or "").strip().lower()
        retryable = payload.get("retryable")
        blocked_status = {"blocked", "locked", "locked_or_readonly", "permission_denied"}
        if retryable is False or status in blocked_status:
            reason = (
                str(payload.get("error") or payload.get("reason") or payload.get("hint") or status).strip()
            )
            safe_tool_name = str(tool_name or payload.get("tool") or "tool")
            return (
                f"Tool {safe_tool_name} returned a non-retryable result ({status or 'error'}). "
                f"Reason: {reason}. Do not retry this call until external conditions change."
            )
        return None

    def _append_tool_execution_messages_then_warnings(self, executions):
        non_retry_warnings = []
        image_messages = []
        for execution in executions if isinstance(executions, list) else []:
            self.Message(
                "tool",
                execution.cleaned_result,
                tool_call_id=execution.call_id,
                name=execution.func_name,
            )
            non_retry_warn = self._build_non_retryable_tool_warning(
                execution.func_name,
                execution.cleaned_result,
            )
            if non_retry_warn:
                non_retry_warnings.append(non_retry_warn)
            image_data = getattr(execution, "image_data", None)
            if image_data:
                image_messages.append(image_data)

        for non_retry_warn in non_retry_warnings:
            self.Message("system", non_retry_warn)
        return image_messages
