"""Managed child entry point; upstream code remains an external dependency."""
import argparse
import os
from pathlib import Path
import secrets
import sys
import threading

from fastapi.responses import JSONResponse
import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    private = root / ".auth" / "workbuddy-service"
    runtime = root / ".runtime" / "workbuddy"
    key = (private / "gateway-key").read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError("Empty gateway credential")
    os.environ.update({
        "WORKBUDDY_PROXY_SOURCE": str(runtime / "workbuddy2api"),
        "WORKBUDDY_ENDPOINT": "https://www.workbuddy.ai",
        "WORKBUDDY_SESSION_FILE": str(private / "session.json"),
        "WORKBUDDY_LOGIN_TTL_SECONDS": "300",
        "WORKBUDDY_LOG_FILE": str(runtime / "logs" / "protocol.jsonl"),
    })
    sys.path.insert(0, str(runtime / "dsh-workbuddy" / "server"))
    from workbuddy_service import create_app
    import codebuddy_proxy
    app = create_app()
    # Do not retain upstream request/response bodies in diagnostic logs.
    codebuddy_proxy.proxy_state.log_file = None

    @app.middleware("http")
    async def authenticate(request, call_next):
        if not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + key):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
        if request.url.path == "/workbuddy/health":
            return JSONResponse({"service": "agentpark-workbuddy", "ready": True, "instance": args.instance})
        request.scope["headers"] = [(k, v) for k, v in request.scope["headers"] if k.lower() != b"authorization"]
        return await call_next(request)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port,
                                          access_log=False, timeout_graceful_shutdown=10))

    def watch_parent():
        sys.stdin.buffer.read()
        server.should_exit = True

    threading.Thread(target=watch_parent, daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
