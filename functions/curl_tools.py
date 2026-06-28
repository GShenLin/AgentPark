import json
import locale
import subprocess

from src.tool_helpers import decode_bytes, redact_sensitive_curl_args, truncate_text


def execute_curl_command(
    url,
    method="GET",
    headers=None,
    data=None,
    extra_args=None,
    timeout=15,
    max_output_chars=12000,
):
    try:
        system_encoding = locale.getpreferredencoding()

        if not isinstance(url, str) or not url.strip():
            return json.dumps({"url": url, "error": "Invalid url", "status": "error"})

        cmd = ["curl", "-L", "-sS"]

        if isinstance(timeout, (int, float)) and timeout > 0:
            cmd += ["--max-time", str(int(timeout))]

        if isinstance(method, str) and method.strip() and method.upper() != "GET":
            cmd += ["-X", method.upper()]

        if headers:
            if isinstance(headers, dict):
                for k, v in headers.items():
                    cmd += ["-H", f"{k}: {v}"]
            elif isinstance(headers, list):
                for h in headers:
                    if isinstance(h, str) and h.strip():
                        cmd += ["-H", h]

        if data is not None:
            if not isinstance(data, str):
                data = str(data)
            cmd += ["--data", data]

        if extra_args:
            if isinstance(extra_args, list):
                cmd += [str(a) for a in extra_args if a is not None]
            else:
                cmd.append(str(extra_args))

        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout)

            stdout = decode_bytes(result.stdout, system_encoding)
            stderr = decode_bytes(result.stderr, system_encoding)
            stdout, stdout_truncated, stdout_total_chars = truncate_text(stdout, max_output_chars)
            stderr, stderr_truncated, stderr_total_chars = truncate_text(stderr, max_output_chars)

            return json.dumps(
                {
                    "command": " ".join(redact_sensitive_curl_args(cmd)),
                    "url": url,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                    "stdout_total_chars": stdout_total_chars,
                    "stderr_total_chars": stderr_total_chars,
                    "returncode": result.returncode,
                    "status": "success" if result.returncode == 0 else "error",
                }
            )

        except subprocess.TimeoutExpired as e:
            stdout = decode_bytes(e.stdout, system_encoding)
            stderr = decode_bytes(e.stderr, system_encoding)
            stdout, stdout_truncated, stdout_total_chars = truncate_text(stdout, max_output_chars)
            stderr, stderr_truncated, stderr_total_chars = truncate_text(stderr, max_output_chars)

            return json.dumps(
                {
                    "command": " ".join(redact_sensitive_curl_args(cmd)),
                    "url": url,
                    "stdout": stdout,
                    "stderr": stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                    "stdout_total_chars": stdout_total_chars,
                    "stderr_total_chars": stderr_total_chars,
                    "error": f"curl execution timed out after {timeout} seconds.",
                    "status": "timeout",
                }
            )

    except Exception as e:
        return json.dumps({"url": url, "error": str(e), "status": "exception"})


execute_curl_command_declaration = {
    "type": "function",
    "function": {
        "name": "execute_curl_command",
        "description": "Fetch a URL via curl (supports headers, method, body, and extra curl args).",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL to request (e.g., 'https://example.com')",
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method (default: GET)",
                    "default": "GET",
                },
                "headers": {
                    "description": "Headers as object map or list of 'Key: Value' strings",
                    "anyOf": [{"type": "object"}, {"type": "array", "items": {"type": "string"}}],
                },
                "data": {
                    "type": "string",
                    "description": "Request body for POST/PUT/PATCH (optional)",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Extra curl args (e.g., ['-H','Accept: application/json','--compressed'])",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 15)",
                    "default": 15,
                },
                "max_output_chars": {
                    "type": "integer",
                    "description": "Max chars kept for stdout/stderr (default: 12000)",
                    "default": 12000,
                },
            },
            "required": ["url"],
        },
    },
}
