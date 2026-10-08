"""Project a saved call into ordinary conversation turns without rewriting history."""
from src.web_backend.node_voice_records import VoiceCallRecord


def voice_history_envelopes(record: dict) -> list[dict]:
    parts = record["parts"]
    if len(parts) != 1 or parts[0].get("type") != "structured":
        raise ValueError("语音历史记录必须包含一份完整的通话文字记录。")
    call = VoiceCallRecord.model_validate(parts[0]["data"])
    if call.history_owner == "node":
        # The ordinary node request/response history already contains these turns.
        return []
    envelopes = []
    for index, line in enumerate(call.lines):
        timing = f"{line.offset_ms / 1000:.1f}s"
        label = f"[语音通话文字记录：{call.started_at}，+{timing}"
        if line.incomplete:
            label += "，此段转写未完成"
        label += "]"
        envelopes.append({
            # Stable identities keep checkpoint fingerprints aligned with each
            # projected turn, including checkpoints covering part of a long call.
            "id": f"{record['id']}:transcript:{index}",
            "role": line.role,
            "parts": [{"type": "text", "text": label + "\n" + line.text}],
            "created_at": record["created_at"],
        })
    return envelopes
