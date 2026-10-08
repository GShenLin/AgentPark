import json
from pathlib import Path
import sys

# .agents/skills/wechat-article/scripts/read.py -> repository root
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from src.wechat_articles.reader import read_article


def main():
    try:
        args = json.load(sys.stdin)
        if not isinstance(args, dict) or set(args) != {"url"}:
            raise ValueError("Expected exactly one argument: url")
        article = read_article(args["url"])
        # ASCII JSON remains lossless even when the host uses a legacy console encoding.
        print(json.dumps(article.to_dict(), ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=True), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
