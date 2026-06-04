import html
import json
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

from src.base_agent import BaseAgent


class AppState:
    def __init__(self, agent: BaseAgent):
        self.agent = agent
        self.in_flight = False
        self.last_error = None
        self._lock = threading.Lock()

    def set_in_flight(self, value: bool):
        with self._lock:
            self.in_flight = value

    def get_in_flight(self) -> bool:
        with self._lock:
            return self.in_flight

    def set_error(self, value):
        with self._lock:
            self.last_error = value

    def get_error(self):
        with self._lock:
            return self.last_error


class HtmlChatRenderer:
    def render(self, messages, in_flight: bool, error=None) -> bytes:
        message_count = len(messages) if isinstance(messages, list) else 0
        parts = [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '  <meta charset="utf-8" />',
            '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
            "  <title>Mission 8 - Local Web Chat (DouBao)</title>",
        ]
        parts.extend(
            [
                "  <style>",
                "    body{font-family:ui-monospace,Consolas,monospace;margin:16px;max-width:980px}",
                "    .msg{border:1px solid #ddd;border-radius:10px;padding:10px 12px;margin:10px 0}",
                "    .role{opacity:.7;font-size:12px;margin-bottom:6px}",
                "    pre{margin:0;white-space:pre-wrap;word-break:break-word}",
                "    form{display:flex;gap:8px;margin-top:14px}",
                "    input[type=text]{flex:1;padding:10px 12px;border-radius:10px;border:1px solid #bbb}",
                "    button{padding:10px 14px;border-radius:10px;border:1px solid #bbb;background:#f6f6f6}",
                "    .status{opacity:.75;margin:12px 0}",
                "  </style>",
                "</head>",
                "<body>",
                "  <h3>Mission 8 - Local Web Chat (DouBao)</h3>",
            ]
        )

        if error:
            parts.append(
                "<div class=\"msg\"><div class=\"role\">error</div>"
                f"<pre>{html.escape(str(error))}</pre></div>"
            )

        if in_flight:
            parts.append('<div class="status" id="status">AI is thinking...</div>')

        for m in messages:
            role = html.escape(str(m.get("role", "")))
            content = m.get("content")
            if isinstance(content, (dict, list)):
                text = json.dumps(content, ensure_ascii=False)
            elif content is None:
                text = ""
            else:
                text = str(content)

            parts.append(
                "<div class=\"msg\">"
                f"<div class=\"role\">{role}</div>"
                f"<pre>{html.escape(text)}</pre>"
                "</div>"
            )

        disabled_attr = " disabled" if in_flight else ""
        parts.extend(
            [
                '<form method="post" action="/send">',
                f'  <input id="message" name="message" type="text" autocomplete="off" autofocus'
                f'{disabled_attr} placeholder="输入消息，回车发送" />',
                f'  <button type="submit"{disabled_attr}>发送</button>',
                "</form>",
                "  <script>",
                f"    const initialMessageCount = {message_count};",
                f"    const wasInFlightAtRender = {str(bool(in_flight)).lower()};",
                "    const form = document.querySelector('form');",
                "    const input = document.getElementById('message');",
                "    const button = form ? form.querySelector('button[type=submit]') : null;",
                "    const statusEl = document.getElementById('status');",
                "    function setDisabled(v){",
                "      if (input) input.disabled = v;",
                "      if (button) button.disabled = v;",
                "    }",
                "    async function pollUntilDone(){",
                "      while (true){",
                "        try {",
                "          const res = await fetch('/state', { cache: 'no-store' });",
                "          if (res.ok){",
                "            const data = await res.json();",
                "            if (!data.in_flight){",
                "              if (wasInFlightAtRender || data.message_count !== initialMessageCount){",
                "                window.location.reload();",
                "              }",
                "              return;",
                "            }",
                "          }",
                "        } catch (e) {",
                "        }",
                "        await new Promise(r => setTimeout(r, 250));",
                "      }",
                "    }",
                "    if (wasInFlightAtRender){",
                "      setDisabled(true);",
                "      pollUntilDone();",
                "    }",
                "    if (form){",
                "      form.addEventListener('submit', () => {",
                "        if (button) button.disabled = true;",
                "        if (statusEl) statusEl.textContent = 'AI is thinking...';",
                "        setTimeout(() => { if (input) input.disabled = true; }, 0);",
                "      });",
                "    }",
                "    window.scrollTo(0, document.body.scrollHeight);",
                "  </script>",
                "</body>",
                "</html>",
            ]
        )

        return "\n".join(parts).encode("utf-8")


def _run_agent_send(state: AppState):
    try:
        state.agent.Send()
    except Exception as e:
        state.set_error(str(e))
        state.agent.Message("assistant", f"Error: {e}")
    finally:
        state.set_in_flight(False)


class ChatHandler(BaseHTTPRequestHandler):
    state: AppState = None
    renderer = HtmlChatRenderer()

    def _send_html(self, body: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        if self.path == "/state":
            self._send_json(
                {
                    "in_flight": self.state.get_in_flight(),
                    "error": self.state.get_error(),
                    "message_count": len(self.state.agent.messages),
                }
            )
            return

        if self.path in ("/", "/index.html"):
            body = self.renderer.render(
                self.state.agent.messages,
                in_flight=self.state.get_in_flight(),
                error=self.state.get_error(),
            )
            self._send_html(body)
            return

        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404)

    def do_POST(self):
        if self.path != "/send":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        message = (parse_qs(raw).get("message") or [""])[0].strip()

        if not message:
            self._redirect("/")
            return

        if self.state.get_in_flight():
            self.state.set_error("Busy: previous request is still running.")
            self._redirect("/")
            return

        self.state.set_error(None)
        self.state.agent.Message("user", message)
        self.state.set_in_flight(True)

        t = threading.Thread(target=_run_agent_send, args=(self.state,), daemon=True)
        t.start()

        self._redirect("/")

    def log_message(self, fmt, *args):
        return
