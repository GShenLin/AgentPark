from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime
from typing import Any

from nodes.agent_skill_loader import SKILL_NAME_LIST
from nodes.gui_agent_actions import (
    is_supported_action_name,
    parse_action,
    parse_action_args,
    validate_action_args,
)
from nodes.gui_agent_capture import capture_screenshot, parse_capture_region
from nodes.gui_agent_executor import execute_gui_action
from nodes.gui_agent_observation import mark_action_feedback_image, update_screen_change_result
from nodes.gui_agent_output import build_gui_agent_response
from nodes.gui_agent_prompts import build_action_repair_prompt, build_planner_prompt
from nodes.gui_agent_runtime import build_mock_plan, run_with_timeout
from nodes.gui_agent_verifier import build_verify_prompt, parse_verify_response
from src.message_protocol import envelope_text, normalize_envelope
from src.providers import create_agent
from src.value_parsing import parse_bool_value, parse_float_value, parse_json_value


def run_gui_agent(node: Any, message: object, context: dict | None = None) -> dict:
    return GuiAgentRun(node, message, context).run()


class GuiAgentRun:
    def __init__(self, node: Any, message: object, context: dict | None = None) -> None:
        self.node = node
        self.context = context or {}
        self.envelope = normalize_envelope(message, default_role="user")

    def run(self) -> dict:
        node = self.node
        ctx = self.context

        provider_id = str(ctx.get("provider_id") or "").strip()
        planner_mode = node.gui_mode
        verify_mode = node.gui_mode
        instruction = self._extract_instruction(self.envelope, ctx)
        system_prompt = str(ctx.get("system_prompt") or "").strip()
        verify_prompt = str(ctx.get("verify_prompt") or "").strip()
        skill_names = SKILL_NAME_LIST.parse(ctx.get("skills"))
        verify_on_finish = parse_bool_value(ctx.get("verify_on_finish"), default=True)
        dry_run = parse_bool_value(ctx.get("dry_run"), default=False)
        planner_timeout_seconds = parse_float_value(ctx.get("planner_timeout_seconds"), default=120.0)
        verify_timeout_seconds = parse_float_value(ctx.get("verify_timeout_seconds"), default=60.0)
        capture_region = parse_capture_region(ctx.get("capture_region"))
        mock_actions = parse_json_value(ctx.get("mock_actions"), [])
        if not isinstance(mock_actions, list):
            mock_actions = []

        if not instruction:
            instruction = "Analyze current GUI and continue."

        run_dir = self._run_dir(ctx)
        self._append_run_log(
            run_dir,
            {
                "event": "run_started",
                "instruction": instruction,
                "provider_id": provider_id,
                "planner_mode": planner_mode,
                "verify_mode": verify_mode,
                "dry_run": dry_run,
                "verify_on_finish": verify_on_finish,
            },
        )
        fallback_images = self._extract_image_fallbacks(self.envelope)
        fallback_index = 0
        step_logs: list[dict] = []
        screenshot_paths: list[str] = []

        def append_step_record(record: dict) -> None:
            step_logs.append(record)
            self._append_run_log(
                run_dir,
                {
                    "event": "step",
                    "step": int(record.get("step") or 0),
                    "status": str(record.get("status") or ""),
                    "action_name": str(record.get("action_name") or ""),
                    "action": str(record.get("action") or ""),
                    "execute": record.get("execute"),
                    "observation": record.get("observation"),
                    "error": record.get("error"),
                    "screenshot_before": record.get("screenshot_before") or record.get("screenshot"),
                    "screenshot_after": record.get("screenshot_after"),
                    "screenshot_after_raw": record.get("screenshot_after_raw"),
                    "screenshot_after_marked": record.get("screenshot_after_marked"),
                },
            )

        planner_agent = None
        if not mock_actions:
            if not provider_id:
                raise ValueError("provider_id is required when mock_actions is empty")
            planner_agent = create_agent(
                provider_id,
                memory_file_path=os.path.join(run_dir, "planner.md"),
                system_prompt=system_prompt if system_prompt else None,
            )
            node._inject_configured_skills(
                planner_agent,
                {"skills": skill_names},
                node_id=ctx.get("node_instance_id") or ctx.get("node_id"),
            )

        finished = False
        final_reason = ""
        history: list[dict] = []
        step_index = 1
        planner_feedback_path = ""

        while True:
            before_path = os.path.join(run_dir, f"step_{step_index:02d}_before.png")
            capture_info, fallback_index = capture_screenshot(
                before_path,
                capture_region,
                fallback_images,
                fallback_index,
            )
            if not parse_bool_value(capture_info.get("ok"), default=False):
                final_reason = f"capture_failed: {capture_info.get('error')}"
                append_step_record(
                    {
                        "step": step_index,
                        "status": "capture_failed",
                        "error": str(capture_info.get("error") or ""),
                    }
                )
                break

            width = int(capture_info.get("width") or 0)
            height = int(capture_info.get("height") or 0)
            screenshot_paths.append(before_path)

            if mock_actions:
                planner_response = build_mock_plan(mock_actions, step_index)
            else:
                try:
                    if planner_agent is None:
                        raise RuntimeError("planner agent not initialized")
                    planner_response = run_with_timeout(
                        lambda: self._call_planner(
                            planner_agent=planner_agent,
                            instruction=instruction,
                            step_index=step_index,
                            screenshot_path=before_path,
                            planner_feedback_path=planner_feedback_path,
                            history=history,
                            mode=planner_mode,
                        ),
                        timeout_seconds=planner_timeout_seconds,
                    )
                except Exception as e:
                    final_reason = f"planner_failed: {str(e)}"
                    append_step_record(
                        {
                            "step": step_index,
                            "status": "planner_failed",
                            "error": str(e),
                            "screenshot": before_path,
                        }
                    )
                    break

            raw_planner_response = planner_response
            repair_record: dict | None = None
            thought, action_text = parse_action(planner_response)
            if not action_text:
                repaired_applied = False
                if planner_agent is not None and not mock_actions:
                    try:
                        repaired_response = self._repair_unsupported_action(
                            planner_agent=planner_agent,
                            instruction=instruction,
                            step_index=step_index,
                            screenshot_path=before_path,
                            history=history,
                            bad_response=raw_planner_response,
                            bad_action_text="",
                            bad_action_name="",
                            execution_error="missing Action line",
                            mode=planner_mode,
                        )
                        repaired_thought, repaired_action_text = parse_action(repaired_response)
                        if repaired_action_text:
                            thought = repaired_thought or thought
                            action_text = repaired_action_text
                            planner_response = repaired_response
                            repaired_applied = True
                        repair_record = {
                            "triggered": True,
                            "bad_action_text": "",
                            "bad_action_name": "",
                            "repair_response": repaired_response,
                            "repair_action": repaired_action_text,
                            "repair_action_name": "",
                            "applied": repaired_applied,
                        }
                    except Exception as e:
                        repair_record = {
                            "triggered": True,
                            "bad_action_text": "",
                            "bad_action_name": "",
                            "applied": False,
                            "error": str(e),
                        }
                if not action_text:
                    final_reason = "planner_no_action"
                    append_step_record(
                        {
                            "step": step_index,
                            "status": "planner_no_action",
                            "planner_response": planner_response,
                            "planner_response_raw": raw_planner_response,
                            "screenshot": before_path,
                            **({"repair": repair_record} if isinstance(repair_record, dict) else {}),
                        }
                    )
                    break

            parsed = parse_action_args(action_text, width, height, node.coordinate_scale)
            action_name = str(parsed.get("name") or "").strip().lower()
            if (
                not is_supported_action_name(action_name, node.supported_action_names)
                and planner_agent is not None
                and not mock_actions
            ):
                try:
                    repaired_response = self._repair_unsupported_action(
                        planner_agent=planner_agent,
                        instruction=instruction,
                        step_index=step_index,
                        screenshot_path=before_path,
                        history=history,
                        bad_response=raw_planner_response,
                        bad_action_text=action_text,
                        bad_action_name=action_name,
                        execution_error="unsupported action name",
                        mode=planner_mode,
                    )
                    repaired_thought, repaired_action_text = parse_action(repaired_response)
                    repaired_parsed = parse_action_args(repaired_action_text, width, height, node.coordinate_scale)
                    repaired_action_name = str(repaired_parsed.get("name") or "").strip().lower()
                    repair_record = {
                        "triggered": True,
                        "bad_action_text": action_text,
                        "bad_action_name": action_name,
                        "repair_response": repaired_response,
                        "repair_action": repaired_action_text,
                        "repair_action_name": repaired_action_name,
                        "applied": False,
                    }
                    if repaired_action_text and is_supported_action_name(
                        repaired_action_name,
                        node.supported_action_names,
                    ):
                        thought = repaired_thought or thought
                        action_text = repaired_action_text
                        parsed = repaired_parsed
                        action_name = repaired_action_name
                        planner_response = repaired_response
                        repair_record["applied"] = True
                except Exception as e:
                    repair_record = {
                        "triggered": True,
                        "bad_action_text": action_text,
                        "bad_action_name": action_name,
                        "applied": False,
                        "error": str(e),
                    }

            validation_error = validate_action_args(parsed)
            if validation_error and planner_agent is not None and not mock_actions:
                try:
                    repaired_response = self._repair_unsupported_action(
                        planner_agent=planner_agent,
                        instruction=instruction,
                        step_index=step_index,
                        screenshot_path=before_path,
                        history=history,
                        bad_response=planner_response,
                        bad_action_text=action_text,
                        bad_action_name=action_name,
                        execution_error=validation_error,
                        mode=planner_mode,
                    )
                    repaired_thought, repaired_action_text = parse_action(repaired_response)
                    repaired_parsed = parse_action_args(repaired_action_text, width, height, node.coordinate_scale)
                    repaired_action_name = str(repaired_parsed.get("name") or "").strip().lower()
                    repaired_validation_error = validate_action_args(repaired_parsed)
                    if repair_record is None:
                        repair_record = {}
                    repair_record["validation_error"] = validation_error
                    repair_record["validation_repair_response"] = repaired_response
                    repair_record["validation_repair_action"] = repaired_action_text
                    repair_record["validation_repair_action_name"] = repaired_action_name
                    repair_record["validation_repair_applied"] = False
                    repair_record["validation_repair_error"] = repaired_validation_error
                    if (
                        repaired_action_text
                        and is_supported_action_name(repaired_action_name, node.supported_action_names)
                        and not repaired_validation_error
                    ):
                        thought = repaired_thought or thought
                        action_text = repaired_action_text
                        parsed = repaired_parsed
                        action_name = repaired_action_name
                        planner_response = repaired_response
                        validation_error = ""
                        repair_record["validation_repair_applied"] = True
                except Exception as e:
                    if repair_record is None:
                        repair_record = {}
                    repair_record["validation_error"] = validation_error
                    repair_record["validation_repair_applied"] = False
                    repair_record["validation_repair_exception"] = str(e)

            if validation_error:
                final_reason = f"invalid_action: {validation_error}"
                append_step_record(
                    {
                        "step": step_index,
                        "status": "invalid_action",
                        "thought": thought,
                        "action": action_text,
                        "action_name": action_name,
                        "parsed_action": parsed,
                        "planner_response": planner_response,
                        "planner_response_raw": raw_planner_response,
                        "error": validation_error,
                        "screenshot_before": before_path,
                        **({"repair": repair_record} if isinstance(repair_record, dict) else {}),
                    }
                )
                break

            step_record = {
                "step": step_index,
                "thought": thought,
                "action": action_text,
                "action_name": action_name,
                "parsed_action": parsed,
                "screenshot_before": before_path,
                "planner_response": planner_response,
                "planner_response_raw": raw_planner_response,
            }
            if isinstance(repair_record, dict):
                step_record["repair"] = repair_record

            if action_name == "finished":
                verify_done = True
                verify_reason = "verify skipped"
                if verify_on_finish:
                    try:
                        verify_done, verify_reason = run_with_timeout(
                            lambda: self._verify_finished(
                                verifier_agent=planner_agent,
                                verify_prompt=verify_prompt,
                                instruction=instruction,
                                screenshot_path=before_path,
                                planner_response=planner_response,
                                mode=verify_mode,
                            ),
                            timeout_seconds=verify_timeout_seconds,
                        )
                    except Exception as e:
                        verify_done = False
                        verify_reason = f"verify_failed: {str(e)}"
                step_record["verify_done"] = verify_done
                step_record["verify_reason"] = verify_reason
                step_record["status"] = "finished_verified" if verify_done else "finished_rejected"
                append_step_record(step_record)
                if verify_done:
                    finished = True
                    final_reason = verify_reason or "finished"
                    break
                history.append(
                    {
                        "step": step_index,
                        "action": action_text,
                        "result": json.dumps(
                            {"ok": False, "kind": "finished", "screen_changed": None, "reason": "finished rejected"},
                            ensure_ascii=False,
                        ),
                    }
                )
                step_index += 1
                continue

            exec_result = execute_gui_action(parsed, dry_run, node.default_wait_seconds)
            step_record["execute"] = exec_result
            if not parse_bool_value(exec_result.get("ok"), default=False):
                exec_result["screen_changed"] = None
                step_record["observation"] = {"screen_changed": None, "note": "execution_failed"}
                step_record["status"] = "execute_failed"
                append_step_record(step_record)
                final_reason = f"execute_failed: {exec_result.get('error')}"
                break

            after_path = os.path.join(run_dir, f"step_{step_index:02d}_after.png")
            capture_after, fallback_index = capture_screenshot(
                after_path,
                capture_region,
                fallback_images,
                fallback_index,
            )
            after_capture_ok = parse_bool_value(capture_after.get("ok"), default=False)
            if not after_capture_ok:
                step_record["screenshot_after_error"] = str(capture_after.get("error") or "")
                planner_feedback_path = ""

            observation = update_screen_change_result(
                exec_result=exec_result,
                before_path=before_path,
                after_path=after_path,
                after_capture_ok=after_capture_ok,
                min_screen_change_ratio=node.min_screen_change_ratio,
            )

            if after_capture_ok:
                after_display_path = after_path
                after_display_path, marker_record = mark_action_feedback_image(
                    run_dir=run_dir,
                    step_index=step_index,
                    after_path=after_path,
                    action_name=action_name,
                    parsed=parsed,
                    exec_result=exec_result,
                )
                step_record.update(marker_record)
                step_record["screenshot_after"] = after_display_path
                screenshot_paths.append(after_display_path)
                planner_feedback_path = after_display_path

            step_record["observation"] = observation

            step_record["status"] = "executed"
            append_step_record(step_record)
            history.append(
                {
                    "step": step_index,
                    "action": action_text,
                    "result": json.dumps(exec_result, ensure_ascii=False),
                }
            )
            step_index += 1

        status = "done" if finished else "stopped"
        self._append_run_log(
            run_dir,
            {
                "event": "run_finished",
                "status": status,
                "finished": finished,
                "reason": final_reason,
                "step_count": len(step_logs),
            },
        )

        return build_gui_agent_response(
            status=status,
            finished=finished,
            final_reason=final_reason,
            instruction=instruction,
            run_dir=run_dir,
            step_logs=step_logs,
            screenshot_paths=screenshot_paths,
            provider_id=provider_id,
            planner_mode=planner_mode,
            verify_mode=verify_mode,
            dry_run=dry_run,
            verify_on_finish=verify_on_finish,
            planner_timeout_seconds=planner_timeout_seconds,
            verify_timeout_seconds=verify_timeout_seconds,
        )

    def _node_dir(self, context: dict) -> str:
        memory_path = self.node._resolve_memory_path(context)
        if memory_path:
            return os.path.dirname(memory_path)
        graph_id = self.node._sanitize_graph_id(context.get("graph_id"))
        node_id = self.node._sanitize_node_id(context.get("node_instance_id") or context.get("node_id") or "gui_agent")
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "memories", graph_id, node_id)

    def _run_dir(self, context: dict) -> str:
        node_dir = self._node_dir(context)
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        path = os.path.join(node_dir, "gui_runs", run_id)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _extract_instruction(message: dict, context: dict) -> str:
        input_text = envelope_text(message).strip()
        fallback_text = str(context.get("instruction") or "").strip()
        return input_text or fallback_text

    @staticmethod
    def _extract_image_fallbacks(message: dict) -> list[str]:
        output: list[str] = []
        parts = message.get("parts") if isinstance(message, dict) else None
        if not isinstance(parts, list):
            return output
        for part in parts:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "").strip().lower() != "resource":
                continue
            res = part.get("resource")
            if not isinstance(res, dict):
                continue
            kind = str(res.get("kind") or "").strip().lower()
            uri = str(res.get("uri") or "").strip()
            if not uri:
                continue
            if kind and kind != "image":
                continue
            raw = uri[7:] if uri.startswith("file://") else uri
            if os.path.isfile(raw):
                output.append(raw)
        return output

    @staticmethod
    def _encode_image_data_url(path: str) -> str:
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        if ext == "jpg":
            ext = "jpeg"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/{ext};base64,{encoded}"

    @staticmethod
    def _append_run_log(run_dir: str, payload: dict) -> None:
        if not run_dir:
            return
        try:
            os.makedirs(run_dir, exist_ok=True)
            log_path = os.path.join(run_dir, "execution.jsonl")
            record = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                **(payload if isinstance(payload, dict) else {"payload": str(payload)}),
            }
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:
            return

    def _repair_unsupported_action(
        self,
        planner_agent: object,
        instruction: str,
        step_index: int,
        screenshot_path: str,
        history: list[dict],
        bad_response: str,
        bad_action_text: str,
        bad_action_name: str,
        mode: str,
        execution_error: str = "",
    ) -> str:
        prompt = build_action_repair_prompt(
            instruction=instruction,
            step_index=step_index,
            history=history,
            bad_response=bad_response,
            bad_action_text=bad_action_text,
            bad_action_name=bad_action_name,
            execution_error=execution_error,
        )
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": self._encode_image_data_url(screenshot_path)}},
        ]
        planner_agent.Message("user", content, persist=False)
        response = planner_agent.Send(run_tools=False, mode=mode)
        return "" if response is None else str(response)

    def _call_planner(
        self,
        planner_agent: object,
        instruction: str,
        step_index: int,
        screenshot_path: str,
        planner_feedback_path: str,
        history: list[dict],
        mode: str,
    ) -> str:
        prompt = build_planner_prompt(
            instruction=instruction,
            step_index=step_index,
            history=history,
        )
        content = [{"type": "text", "text": prompt}]
        if screenshot_path and os.path.isfile(screenshot_path):
            content.append({"type": "image_url", "image_url": {"url": self._encode_image_data_url(screenshot_path)}})
        if (
            planner_feedback_path
            and planner_feedback_path != screenshot_path
            and os.path.isfile(planner_feedback_path)
        ):
            content.append(
                {
                    "type": "text",
                    "text": (
                        "Previous action feedback image with exact executed coordinate markers. "
                        "Use it to correct coordinate offset in the next action."
                    ),
                }
            )
            content.append(
                {"type": "image_url", "image_url": {"url": self._encode_image_data_url(planner_feedback_path)}}
            )
        planner_agent.Message("user", content, persist=False)
        response = planner_agent.Send(run_tools=False, mode=mode)
        return "" if response is None else str(response)

    def _verify_finished(
        self,
        verifier_agent: object | None,
        verify_prompt: str,
        instruction: str,
        screenshot_path: str,
        planner_response: str,
        mode: str,
    ) -> tuple[bool, str]:
        if verifier_agent is None:
            return True, "verify skipped (no verifier)"
        prompt = build_verify_prompt(verify_prompt, instruction, planner_response)
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": self._encode_image_data_url(screenshot_path)}},
        ]
        verifier_agent.Message("user", content, persist=False)
        response = verifier_agent.Send(run_tools=False, mode=mode)
        return parse_verify_response(response)
