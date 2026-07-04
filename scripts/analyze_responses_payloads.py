from __future__ import annotations

import argparse
import json
import os
import sys


def _bootstrap_repo_root() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def main(argv: list[str] | None = None) -> int:
    _bootstrap_repo_root()
    from src.providers.responses_payload_analysis import analyze_responses_payload_log

    parser = argparse.ArgumentParser(description="Summarize AgentPark OpenAI Responses payload logs.")
    parser.add_argument("path", help="Path to responses_payloads.jsonl")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args(argv)

    analysis = analyze_responses_payload_log(args.path)
    print(json.dumps(analysis, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if analysis.get("exists") else 2


if __name__ == "__main__":
    raise SystemExit(main())
