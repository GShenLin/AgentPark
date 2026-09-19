import json
import os
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE))

from src.knowledge.skill import execute


def main():
    try:
        arguments = json.load(sys.stdin)
        if not isinstance(arguments, dict) or "action" in arguments:
            raise ValueError("工具参数必须是对象，操作由工具名称决定，不接受 action 参数")
        result = execute(WORKSPACE, {**arguments, "action": os.environ["AGENTPARK_SKILL_SCRIPT_ID"]})
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=True), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
