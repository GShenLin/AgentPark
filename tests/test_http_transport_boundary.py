"""Production HTTP clients must use the existing curl transport.

TestClient/mocked HTTP clients in tests and internals of third-party SDKs are
outside this boundary. URL parsing and the file-URI converter do not perform IO.
"""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"requests", "httpx", "httpx2", "aiohttp", "urllib3", "httpcore",
             "httplib2", "http.client", "urllib.request", "urllib.error"}


def forbidden(module):
    return any(module == name or module.startswith(name + ".") for name in FORBIDDEN)


def test_production_http_uses_curl():
    paths = list(ROOT.glob("*.py"))
    for folder in ("src", "functions", "nodes", "scripts", "deploy", "plugins"):
        paths.extend((ROOT / folder).rglob("*.py"))
    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.module == "urllib.request" and {a.name for a in node.names} == {"url2pathname"}:
                    continue
                names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Call) and ast.unparse(node.func) in {"__import__", "importlib.import_module"}:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    names = [node.args[0].value]
            for name in names:
                if forbidden(name):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert not violations, "Use CurlHttpTransport instead:\n" + "\n".join(violations)
