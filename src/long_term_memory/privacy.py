"""Deterministic removal of configured credentials plus recognizable credential syntax."""
import re


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\b(?:sk-|sk-proj-)[A-Za-z0-9_-]{12,}", "[REDACTED]", text)
    text = re.sub(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]+=*", r"\1[REDACTED]", text)
    text = re.sub(r'(?i)([?&](?:token|key|api_key|access_token|signature)=)[^&\s"<>]+', r"\1[REDACTED]", text)
    return text
