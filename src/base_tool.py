import queue
import re
import threading

from .tool_module_loader import load_tool_module
from .tool_invocation import invoke_tool_function
from .tool_load_errors import ToolLoadError
from .tool_event_protocol import build_tool_call_end
from .tool_event_protocol import build_tool_call_start
from .tool_event_protocol import elapsed_ms
from .tool_event_protocol import emit_tool_event
from .tool_event_protocol import now_monotonic
from .tool_call_protocol import ToolCallEnvelope, ToolCallExecution
from .tool_execution_result import build_error_result
from .tool_execution_result import normalize_tool_execution_result
from .tool_execution_result import ToolExecutionResult
from .tool_result_processing import process_tool_result
from .tool_result_processing import process_tool_result_outcome
from .tool_timeout_config import resolve_tool_timeout_seconds
from .tool_timeout_config import ToolTimeoutConfigError
from .tool_preflight_policy import READ_ONLY_PREFLIGHT_TOOLS
from .tool_preflight_policy import build_preflight_prompt
from .tool_preflight_policy import filter_tool_declarations
from .tool_preflight_policy import is_safe_console_command


class BaseTool:
    _TOOL_FUNCTION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

    def __init__(self, agent):
        self.agent = agent
        self.tool_declarations = []
        self.function_map = {}
        self.preflight_enabled = True
        self._tool_policy_mode = "normal"
        self._tool_policy_allowed_tools = None

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
                                    self._register_tool_aliases(module, func_name, func)
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

    @classmethod
    def _validate_tool_function_name(cls, func_name, tool_name, declaration_name):
        if not isinstance(func_name, str) or not func_name.strip():
            raise ValueError(f"Tool declaration {tool_name}.{declaration_name} has an empty function name.")
        if not cls._TOOL_FUNCTION_NAME_RE.fullmatch(func_name):
            raise ValueError(
                f"Tool declaration {tool_name}.{declaration_name} uses invalid function name {func_name!r}. "
                "Function names must match ^[a-zA-Z0-9_-]+$."
            )

    def _register_tool_aliases(self, module, func_name, func):
        aliases = getattr(module, "tool_function_aliases", None)
        if not isinstance(aliases, dict):
            return
        raw_aliases = aliases.get(func_name)
        if not isinstance(raw_aliases, (list, tuple, set)):
            return
        for alias in raw_aliases:
            if isinstance(alias, str) and alias.strip():
                alias_name = alias.strip()
                existing_func = self.function_map.get(alias_name)
                if existing_func is not None and existing_func is not func:
                    raise ValueError(
                        f"Tool function alias {alias_name!r} is registered by multiple callables."
                    )
                self.function_map[alias_name] = func

    def execute_tool(self, name, args):
        return self.execute_tool_result(name, args).model_output()

    def execute_tool_result(self, name, args):
        if self._tool_policy_mode == "preflight":
            allowed = self._tool_policy_allowed_tools
            if isinstance(allowed, set) and name not in allowed:
                return build_error_result(
                    "permission_denied",
                    tool_name=name,
                    error=f"Tool {name} is not allowed in preflight.",
                )
            if name == "execute_console_command":
                command = ""
                if isinstance(args, dict):
                    command = str(args.get("command") or "")
                if not is_safe_console_command(command):
                    return build_error_result(
                        "blocked",
                        tool_name=name,
                        error="Unsafe console command blocked in preflight.",
                        result={
                            "status": "blocked",
                            "reason": "Unsafe console command blocked in preflight.",
                            "command": command,
                        },
                    )

        if name not in self.function_map:
            return build_error_result("error", tool_name=name, error=f"Tool {name} not found.")

        func = self.function_map[name]
        try:
            timeout_seconds = self._resolve_tool_timeout_seconds(name=name, func=func)
        except ToolTimeoutConfigError as exc:
            return build_error_result("error", tool_name=name, error=str(exc))
        if timeout_seconds is None:
            try:
                return normalize_tool_execution_result(self._invoke_tool_function(func, args), tool_name=name)
            except Exception as e:
                return build_error_result("exception", tool_name=name, error=f"{type(e).__name__}: {str(e)}")

        result_queue = queue.Queue(maxsize=1)

        def _target():
            try:
                result_queue.put(
                    (
                        "ok",
                        normalize_tool_execution_result(
                            self._invoke_tool_function(func, args),
                            tool_name=name,
                        ),
                    )
                )
            except Exception as e:
                result_queue.put(
                    (
                        "error",
                        build_error_result(
                            "exception",
                            tool_name=name,
                            error=f"{type(e).__name__}: {str(e)}",
                        ),
                    )
                )

        worker = threading.Thread(target=_target, daemon=True, name=f"tool-{name}")
        worker.start()
        worker.join(timeout=timeout_seconds)

        if worker.is_alive():
            return build_error_result(
                "timeout",
                tool_name=name,
                error=f"Tool execution exceeded {timeout_seconds:.2f}s.",
            )

        if result_queue.empty():
            return build_error_result("exception", tool_name=name, error="Tool worker returned no result.")

        state, payload = result_queue.get()
        if state == "error":
            if isinstance(payload, ToolExecutionResult):
                return payload
            return build_error_result("exception", tool_name=name, error=str(payload))
        return payload

    def execute_tool_call(self, call):
        if not isinstance(call, ToolCallEnvelope):
            raise TypeError("execute_tool_call requires a ToolCallEnvelope")
        event_callback = self._resolve_tool_event_callback()
        started_at = now_monotonic()
        emit_tool_event(event_callback, build_tool_call_start(call))
        tool_result = self.execute_tool_result(call.name, call.arguments)
        processed = process_tool_result_outcome(tool_result.model_output())
        cleaned_result = processed.cleaned_result
        image_data = processed.image_data
        status = tool_result.status
        error = tool_result.error
        emit_tool_event(
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
        return ToolCallExecution(
            func_name=call.name,
            call_id=call.call_id,
            cleaned_result=cleaned_result,
            image_data=image_data,
            status=status,
            error=error,
            diagnostics=processed.diagnostics,
        )

    def _resolve_tool_event_callback(self):
        callback = getattr(self.agent, "tool_event_callback", None)
        if callable(callback):
            return callback
        return None

    def _invoke_tool_function(self, func, args):
        return invoke_tool_function(func, args, agent=self.agent)

    def _resolve_tool_timeout_seconds(self, name=None, func=None):
        return resolve_tool_timeout_seconds(
            config=getattr(self.agent, "config", None),
            name=name,
            func=func,
        )

    def run_task(self, task, use_preflight=None):
        if use_preflight is None:
            use_preflight = bool(self.preflight_enabled)

        if use_preflight:
            self._run_preflight(task)

        self.agent.Message("user", f"Mission Start.\n\n{task}")
        return self._send_with_optional_kwargs(run_tools=True)

    def _run_preflight(self, task, max_attempts=2):
        allowed_tools = READ_ONLY_PREFLIGHT_TOOLS
        preflight_tools = self._filter_tool_declarations(allowed_tools)
        self._tool_policy_mode = "preflight"
        self._tool_policy_allowed_tools = allowed_tools

        start_len = len(self.agent.messages)
        try:
            prompt = self._build_preflight_prompt(task, strict=False)
            self.agent.Message("user", prompt)
            self._send_with_optional_kwargs(tools=preflight_tools, run_tools=True)

            attempts = 1
            while attempts < max_attempts and not self._has_tool_activity_since(start_len):
                self.agent.Message("user", self._build_preflight_prompt(task, strict=True))
                self._send_with_optional_kwargs(tools=preflight_tools, run_tools=True)
                attempts += 1
        finally:
            self._tool_policy_mode = "normal"
            self._tool_policy_allowed_tools = None

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
        return build_preflight_prompt(task, strict=strict)

    def _filter_tool_declarations(self, allowed_names):
        return filter_tool_declarations(self.tool_declarations, allowed_names)

    def _is_safe_console_command(self, command):
        return is_safe_console_command(command)

    def process_tool_result(self, tool_result):
        return process_tool_result(tool_result)

    def _resize_base64_image(self, base64_string, max_size=(1024, 1024)):
        from .tool_result_processing import resize_base64_image

        return resize_base64_image(base64_string, max_size=max_size)
