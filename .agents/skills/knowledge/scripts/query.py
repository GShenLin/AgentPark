import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.knowledge.skill import execute
from src.knowledge.node_access import knowledge_ids


def main():
    try:
        arguments = json.load(sys.stdin)
        if not isinstance(arguments, dict) or "action" in arguments:
            raise ValueError("工具参数必须是对象，操作由工具名称决定，不接受 action 参数")
        workspace = Path(os.environ["AGENTPARK_WORKSPACE_ROOT"])
        if not workspace.is_absolute() or not workspace.is_dir():
            raise ValueError("Knowledge requires an absolute workspace directory")
        ids = knowledge_ids(json.loads(os.environ["AGENTPARK_KNOWLEDGE_IDS"]))
        result = execute(workspace, {**arguments, "action": os.environ["AGENTPARK_SKILL_SCRIPT_ID"]},
                         library_ids=ids)
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=True), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
