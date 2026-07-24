import json
import re
import threading

from .tool_module_loader import load_tool_module
from .tool_load_errors import ToolLoadError
from .tool_function_execution import execute_local_tool_function

from .tool_event_protocol import build_tool_call_end
from .tool_event_protocol import build_tool_call_start
from .tool_event_protocol import elapsed_ms
from .tool_event_protocol import emit_tool_event
from .tool_event_protocol import now_monotonic
from .tool_call_protocol import ToolCallEnvelope, ToolCallExecution
from .tool_execution_result import build_error_result
from .tool_execution_result import build_user_stopped_result
from .tool_execution_result import normalize_tool_execution_result
from .tool_result_processing import process_tool_result
from .tool_result_processing import process_tool_result_outcome
from .tool_timeout_config import resolve_tool_timeout_seconds
from .tool_timeout_config import ToolTimeoutConfigError
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import cancel_source_from_agent
from src.runtime_cancellation import combine_cancel_sources
from src.runtime_cancellation import is_cancel_requested
from src.runtime_cancellation import raise_if_cancel_requested
from src.runtime_cancellation import tool_call_cancellation_scope
from src.remote_workspace import dispatch_remote_workspace_tool


class BaseTool:
    _TOOL_FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
    _PREFLIGHT_TOOL_NAMES = {
        "read_file",
        "rg_search_text",
        "rg_list_files",
        "workspace_exec",
        "execute_console_command",
    }

    def __init__(self, agent):
        self.agent = agent
        self.tool_declarations = []
        self.function_map = {}
        self.preflight_enabled = True

    def addTool(self, tool_name):
        try:
            module = load_tool_module(tool_name)

            for attr_name in dir(module):
                if attr_name.endswith("_declaration"):
                    declaration = getattr(module, attr_name)
                    if isinstance(declaration, dict):
                        func_name = None
                        if "function" in declaration and "name" in declaration["function"]:
                            func_name = declaration["function"]["name"]
                        elif "name" in declaration:
                            func_name = declaration["name"]

                        if func_name:
                            self._validate_tool_function_name(func_name, tool_name, attr_name)
                            if hasattr(module, func_name):
                                func = getattr(module, func_name)
                                if callable(func):
                                    existing_func = self.function_map.get(func_name)
                                    if existing_func is not None and existing_func is not func:
                                        raise ValueError(
                                            f"Tool function name {func_name!r} is declared by multiple callables."
                                        )
                                    if existing_func is None:
                                        self.tool_declarations.append(declaration)
                                    self.function_map[func_name] = func
                                else:
                                    raise ToolLoadError(
                                        f"Tool declaration {tool_name}.{attr_name} points to non-callable "
                                        f"function {func_name!r}."
                                    )
                            else:
                                raise ToolLoadError(
                                    f"Tool declaration {tool_name}.{attr_name} references missing "
                                    f"function {func_name!r}."
                                )

        except ImportError as e:
            raise ToolLoadError(f"Error loading tool module {tool_name}: {e}") from e
        except ValueError:
            raise
        except ToolLoadError:
            raise
        except Exception as e:
            raise ToolLoadError(f"Error processing tool module {tool_name}: {e}") from e

    def register_external_tool(self, declaration, func):
        if not isinstance(declaration, dict):
            raise ToolLoadError("External tool declaration must be an object.")
        if not callable(func):
            raise ToolLoadError("External tool function must be callable.")

        func_name = self._extract_tool_function_name(declaration)
        self._validate_tool_function_name(func_name, "external", "declaration")
        existing_func = self.function_map.get(func_name)
        if existing_func is not None and existing_func is not func:
            raise ValueError(f"Tool function name {func_name!r} is declared by multiple callables.")
        if existing_func is None:
            self.tool_declarations.append(declaration)
        self.function_map[func_name] = func

    @staticmethod
    def _extract_tool_function_name(declaration):
        if "function" in declaration and isinstance(declaration["function"], dict):
            return declaration["function"].get("name")
        return declaration.get("name")

    @classmethod
    def _validate_tool_function_name(cls, func_name, tool_name, declaration_name):
        if not isinstance(func_name, str) or not func_name.strip():
            raise ValueError(f"Tool declaration {tool_name}.{declaration_name} has an empty function name.")
        if not cls._TOOL_FUNCTION_NAME_RE.fullmatch(func_name):
            raise ValueError(
                f"Tool declaration {tool_name}.{declaration_name} uses invalid function name {func_name!r}. "
                "Function names must match ^[a-zA-Z0-9_-]+$."
            )

    def execute_tool(self, name, args):
        return self.execute_tool_result(name, args).model_output()

    def execute_tool_result(self, name, args):
        cancel_source = cancel_source_from_agent(self.agent)
        try:
            raise_if_cancel_requested(cancel_source)
        except CancellationRequested as exc:
            return build_error_result("stopped", tool_name=name, error=str(exc))

        if name not in self.function_map:
            return build_error_result("error", tool_name=name, error=f"Tool {name} not found.")

        func = self.function_map[name]
        try:
            remote_timeout_seconds = resolve_tool_timeout_seconds(
                config=getattr(self.agent, "config", None),
                name=name,
                func=func,
                default_timeout=0,
            )
            remote_handled, remote_result = dispatch_remote_workspace_tool(
                self.agent,
                name,
                args,
                timeout_seconds=remote_timeout_seconds,
            )
            if remote_handled:
                return normalize_tool_execution_result(remote_result, tool_name=name)
        except CancellationRequested as exc:
            return build_error_result("stopped", tool_name=name, error=str(exc))
        except ToolTimeoutConfigError as exc:
            return build_error_result("error", tool_name=name, error=str(exc))
        except Exception as exc:
            return build_error_result("exception", tool_name=name, error=f"{type(exc).__name__}: {str(exc)}")
        try:
            timeout_seconds = resolve_tool_timeout_seconds(
                config=getattr(self.agent, "config", None),
                name=name,
                func=func,
            )
        except ToolTimeoutConfigError as exc:
            return build_error_result("error", tool_name=name, error=str(exc))
        return execute_local_tool_function(
            func=func,
            args=args,
            agent=self.agent,
            tool_name=name,
            timeout_seconds=timeout_seconds,
            cancel_source=cancel_source,
        )

    def execute_tool_call(self, call):
        if not isinstance(call, ToolCallEnvelope):
            raise TypeError("execute_tool_call requires a ToolCallEnvelope")
        event_callback = self._resolve_tool_event_callback()
        node_cancel_source = cancel_source_from_agent(self.agent)
        call_cancel_event = self._begin_tool_call_cancellation(call.call_id)
        combined_cancel_source = combine_cancel_sources(node_cancel_source, call_cancel_event)
        started_at = now_monotonic()
        try:
            emit_tool_event(event_callback, build_tool_call_start(call))
            with tool_call_cancellation_scope(combined_cancel_source):
                tool_result = self.execute_tool_result(call.name, call.arguments)
            if (
                tool_result.status == "stopped"
                and is_cancel_requested(call_cancel_event)
                and not is_cancel_requested(node_cancel_source)
            ):
                tool_result = build_user_stopped_result(tool_name=call.name)
            processed = process_tool_result_outcome(tool_result.model_output())
            cleaned_result = processed.cleaned_result
            image_data = processed.image_data
            status = tool_result.status
            error = tool_result.error
            event_feedback = emit_tool_event(
                event_callback,
                build_tool_call_end(
                    call,
                    status=status,
                    duration_ms=elapsed_ms(started_at),
                    error=error,
                    result=cleaned_result,
                    diagnostics=processed.diagnostics,
                ),
            )
            cleaned_result = _attach_memory_persistence_warning(cleaned_result, event_feedback)
            return ToolCallExecution(
                func_name=call.name,
                call_id=call.call_id,
                cleaned_result=cleaned_result,
                image_data=image_data,
                status=status,
                error=error,
                diagnostics=processed.diagnostics,
            )
        finally:
            self._end_tool_call_cancellation(call.call_id, call_cancel_event)

    def _begin_tool_call_cancellation(self, call_id):
        callback = getattr(self.agent, "_agentpark_begin_tool_call_cancellation", None)
        if callable(callback):
            return callback(call_id)
        return threading.Event()

    def _end_tool_call_cancellation(self, call_id, event):
        callback = getattr(self.agent, "_agentpark_end_tool_call_cancellation", None)
        if callable(callback):
            callback(call_id, event)

    def _resolve_tool_event_callback(self):
        callback = getattr(self.agent, "tool_event_callback", None)
        if callable(callback):
            return callback
        return None

    def run_task(self, task, use_preflight=None):
        if use_preflight is None:
            use_preflight = bool(self.preflight_enabled)

        if use_preflight:
            self._run_preflight(task)

        self.agent.Message("user", f"Mission Start.\n\n{task}")
        return self._send_with_optional_kwargs(run_tools=True)

    def _run_preflight(self, task, max_attempts=2):
        preflight_tools = self._filter_tool_declarations(self._PREFLIGHT_TOOL_NAMES)

        start_len = len(self.agent.messages)
        prompt = self._build_preflight_prompt(task, strict=False)
        self.agent.Message("user", prompt)
        self._send_with_optional_kwargs(tools=preflight_tools, run_tools=True)

        attempts = 1
        while attempts < max_attempts and not self._has_tool_activity_since(start_len):
            self.agent.Message("user", self._build_preflight_prompt(task, strict=True))
            self._send_with_optional_kwargs(tools=preflight_tools, run_tools=True)
            attempts += 1

    def _send_with_optional_kwargs(self, tools=None, run_tools=None):
        kwargs = {}
        if "tools" in self.agent.Send.__code__.co_varnames:
            kwargs["tools"] = tools
        if run_tools is not None and "run_tools" in self.agent.Send.__code__.co_varnames:
            kwargs["run_tools"] = run_tools
        return self.agent.Send(**kwargs) if kwargs else self.agent.Send()

    def _has_tool_activity_since(self, start_index):
        for msg in self.agent.messages[start_index:]:
            if msg.get("role") in ("function", "tool"):
                return True
            if msg.get("tool_calls"):
                return True
            if msg.get("function_call"):
                return True
            if msg.get("parts"):
                parts = msg.get("parts")
                if isinstance(parts, list):
                    for part in parts:
                        if isinstance(part, dict) and "functionCall" in part:
                            return True
        return False

    def _build_preflight_prompt(self, task, strict=False):
        base = (
            "Before you start executing the task, you must first enter an information-gathering phase.\n"
            "Requirements:\n"
            "1) Use function tools to collect key information (prefer read-only tools: read_file/rg_list_files/rg_search_text; use execute_console_command only when necessary).\n"
            "2) Parallelize independent function calls directly. For multi-stage workspace investigation, use workspace_exec: stages are sequential and operations inside a stage are concurrent.\n"
            "3) After gathering, output exactly one JSON object (no code fences, no explanations) containing: facts/assumptions/open_questions/plan.\n"
            "4) Do not deliver the final result in this phase.\n\n"
            f"Task: {task}\n"
        )
        if strict:
            return (
                "You did not call any tools as required. You must call at least one tool before outputting the JSON.\n\n"
                + base
            )
        return base

    def _filter_tool_declarations(self, allowed_names):
        allowed = allowed_names if isinstance(allowed_names, set) else set(allowed_names or [])
        filtered = []
        for declaration in self.tool_declarations or []:
            name = None
            if isinstance(declaration, dict):
                func = declaration.get("function")
                if isinstance(func, dict):
                    name = func.get("name")
                elif "name" in declaration:
                    name = declaration.get("name")
            if isinstance(name, str) and name in allowed:
                filtered.append(declaration)
        return filtered

    def process_tool_result(self, tool_result):
        return process_tool_result(tool_result)

    def _resize_base64_image(self, base64_string, max_size=(1024, 1024)):
        from .tool_result_processing import resize_base64_image

        return resize_base64_image(base64_string, max_size=max_size)


def _attach_memory_persistence_warning(cleaned_result, event_feedback):
    if not isinstance(event_feedback, dict):
        return cleaned_result
    warning = str(event_feedback.get("memory_persistence_warning") or "").strip()
    if not warning:
        return cleaned_result
    if isinstance(cleaned_result, dict):
        payload = dict(cleaned_result)
        payload["memory_persistence_warning"] = warning
        return payload
    if isinstance(cleaned_result, str):
        text = cleaned_result.strip()
        if text:
            try:
                payload = json.loads(text)
            except Exception:
                payload = None
            if isinstance(payload, dict):
                payload["memory_persistence_warning"] = warning
                return json.dumps(payload, ensure_ascii=False)
        return json.dumps({"result": cleaned_result, "memory_persistence_warning": warning}, ensure_ascii=False)
    return {"result": cleaned_result, "memory_persistence_warning": warning}
