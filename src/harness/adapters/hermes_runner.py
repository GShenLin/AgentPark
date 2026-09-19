"""Standalone bridge executed by Hermes's Python, never imported into AgentPark's environment.

The real Hermes SDK owns inference and tool execution. This bridge owns the JSONL wire contract
and atomic conversation snapshot so every process uses the current short-lived gateway lease.
"""
from __future__ import annotations

from contextlib import closing, redirect_stdout
import json
import os
from pathlib import Path
import sys
import threading
import uuid


CONVERSATION_INSTRUCTION = (
    "AgentPark conversation continuity: the supplied earlier user, assistant, and tool messages "
    "are this node's current conversation, carried across turns. Use those messages as primary "
    "evidence when the user asks what we previously or recently discussed: answer with a direct "
    "recap of the visible exchange. Use session_search for conversations outside the supplied "
    "history. Its browse mode excludes the current live session, so zero results only means "
    "no other sessions were returned; it says nothing about the messages already in context. "
    "Never describe the current conversation as missing or unavailable when its messages are "
    "present. If an earlier assistant claimed there was no history but earlier messages are "
    "visible, correct that claim and recap the messages instead of repeating it. Do not "
    "speculate about a device or profile change without evidence."
)


def completed_turn(result: object) -> tuple[str, list[dict]]:
    if not isinstance(result, dict):
        raise ValueError("Hermes run_conversation must return a result object.")
    if result.get("failed") or result.get("error") or result.get("interrupted") or result.get("completed") is not True:
        raise RuntimeError(f"Hermes turn failed: {result.get('error') or result.get('turn_exit_reason') or result.get('final_response')}")
    if result.get("cleanup_errors"):
        raise RuntimeError(f"Hermes cleanup failed: {result['cleanup_errors']}")
    final = result.get("final_response")
    messages = result.get("messages")
    if not isinstance(final, str) or not isinstance(messages, list) or not all(
            isinstance(message, dict) and isinstance(message.get("role"), str) for message in messages):
        raise ValueError("Hermes result requires final_response and conversation messages.")
    return final, messages


def flush_history(agent, messages: list[dict]) -> None:
    # Hermes logs some persistence failures and returns False. They must reach the
    # host instead of reporting a successful turn whose searchable history was lost.
    if agent._flush_messages_to_session_db(messages) is not True:
        raise RuntimeError("Hermes could not persist conversation messages to its session database.")


def main() -> None:
    wire = sys.stdout
    lock = threading.Lock()

    def emit(event: dict) -> None:
        with lock:
            wire.write(json.dumps(event, ensure_ascii=False) + "\n")
            wire.flush()

    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("Hermes runner input must be an object.")
        for key in ("text", "model", "base_url", "instruction", "state_dir", "reasoning_effort"):
            if not isinstance(request.get(key), str):
                raise ValueError(f"Hermes runner requires string {key}.")
        state_path = Path(request["state_dir"]) / "conversation.json"
        history = []
        session_id = "agentpark-" + uuid.uuid4().hex
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            if (not isinstance(state, dict) or state.get("schema") != 1
                    or not isinstance(state.get("session_id"), str) or not state["session_id"]
                    or not isinstance(state.get("messages"), list)
                    or not all(isinstance(message, dict) and isinstance(message.get("role"), str)
                               for message in state["messages"])):
                raise ValueError("Invalid Hermes conversation snapshot.")
            history, session_id = state["messages"], state["session_id"]

        def text_delta(text):
            if text is not None:
                if not isinstance(text, str):
                    raise ValueError("Hermes text delta must be a string.")
                emit({"type": "text", "text": text})

        def thinking(text):
            if not isinstance(text, str):
                raise ValueError("Hermes reasoning delta must be a string.")
            emit({"type": "thinking", "text": text})

        def tool_start(call_id, name, arguments):
            emit({"type": "tool_start", "id": call_id, "name": name, "arguments": arguments})

        def tool_end(call_id, name, arguments, result):
            emit({"type": "tool_end", "id": call_id, "name": name, "output": result,
                  "error": isinstance(result, dict) and bool(result.get("error"))})

        # Hermes diagnostics and imports must never mix with our structured stdout.
        with redirect_stdout(sys.stderr):
            from hermes_state import SessionDB
            from run_agent import AIAgent
            # One database handle per runner, shared by inference and native recall.
            # The runner owns the handle; the SDK owns transcript serialization/dedup.
            with closing(SessionDB(db_path=Path(request["state_dir"]) / "home" / "state.db")) as session_db:
                saved_session = session_db.get_session(session_id)
                if saved_session and saved_session.get("end_reason") == "agent_close":
                    # Resume the selected conversation after a previous SDK owner closed it.
                    # Compression/reset boundaries must retain their native meaning.
                    session_db.reopen_session(session_id)
                agent = AIAgent(
                    model=request["model"], base_url=request["base_url"],
                    api_key=os.environ["AGENTPARK_HARNESS_TOKEN"], provider="custom", api_mode="codex_responses",
                    requested_provider="custom:agentpark", quiet_mode=True, session_id=session_id,
                    session_db=session_db,
                    reasoning_config=({"enabled": True, "effort": request["reasoning_effort"]}
                                      if request["reasoning_effort"] else None),
                    # The local gateway owns the provider vocabulary. Hermes's
                    # Codex model catalog must not clamp a provider's max to xhigh.
                    request_overrides=({"reasoning": {"effort": request["reasoning_effort"]}}
                                       if request["reasoning_effort"] else None),
                    ephemeral_system_prompt="\n\n".join(filter(None, [request["instruction"], CONVERSATION_INSTRUCTION])),
                    stream_delta_callback=text_delta, reasoning_callback=thinking,
                    tool_start_callback=tool_start, tool_complete_callback=tool_end,
                    skip_background_review=True, run_budget_seconds=request["timeout"],
                )
                try:
                    agent.session_cwd = os.getcwd()
                    # Ending this subprocess is not ending the node's conversation.
                    agent._end_session_on_close = False
                    if history:
                        # Restore any snapshot messages not yet in native storage before
                        # Hermes treats conversation_history as already durable.
                        flush_history(agent, history)
                    result = agent.run_conversation(user_message=request["text"], conversation_history=history, task_id=session_id)
                    final, messages = completed_turn(result)
                    flush_history(agent, messages)
                    # Context compression may rotate Hermes's native session identity.
                    session_id = agent.session_id
                    if not isinstance(session_id, str) or not session_id:
                        raise ValueError("Hermes returned an invalid session identity.")
                finally:
                    agent.close()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema": 1, "session_id": session_id, "messages": messages},
                                        ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, state_path)
        emit({"type": "result", "text": final})
    except Exception as exc:
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
