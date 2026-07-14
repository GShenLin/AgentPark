from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


SUPPORTED_PROVIDER_TYPES = {"openai", "doubao", "claude", "gemini", "grok", "zhipu", "hyper3d", "deepseek"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _check_json_files(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in (
        "config/config.json",
        "config/moduleProvider.json",
        "config/ProviderLimit.json",
    ):
        path = root / relative
        if not path.exists():
            errors.append(f"missing JSON file: {relative}")
            continue
        try:
            _load_json(path)
        except Exception as exc:
            errors.append(f"invalid JSON in {relative}: {exc}")
    return errors


def _providers_from_config(root: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(root / "config/moduleProvider.json")
    providers = payload.get("providers") if isinstance(payload, dict) else None
    return providers if isinstance(providers, dict) else {}


def _check_provider_types(providers: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for provider_id, provider in sorted(providers.items()):
        provider_type = str((provider or {}).get("type") or "").strip().lower()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            errors.append(
                f"provider {provider_id!r} has unsupported type {provider_type!r}; "
                f"supported={sorted(SUPPORTED_PROVIDER_TYPES)}"
            )
    return errors


def _check_loader_contract(root: Path) -> list[str]:
    errors: list[str] = []
    os.environ["AGENTPARK_CONFIG_PATH"] = str(root / "config/moduleProvider.json")
    try:
        from src.config_loader import ConfigLoader

        providers = ConfigLoader().get_all_providers()
    except Exception as exc:
        return [f"ConfigLoader failed for local provider config: {type(exc).__name__}: {exc}"]
    if not isinstance(providers, dict) or not providers:
        errors.append("ConfigLoader returned no providers")
    return errors


def _check_provider_factory(root: Path, providers: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    os.environ["AGENTPARK_CONFIG_PATH"] = str(root / "config/moduleProvider.json")
    try:
        from src.providers import create_agent
    except Exception as exc:
        return [f"failed to import provider factory: {type(exc).__name__}: {exc}"]

    skipped_missing_key: list[str] = []
    for provider_id, provider in sorted(providers.items()):
        if not str((provider or {}).get("apiKey") or "").strip():
            skipped_missing_key.append(provider_id)
            continue
        try:
            create_agent(provider_id, internal_memory_enabled=False)
        except Exception as exc:
            errors.append(f"create_agent({provider_id!r}) failed: {type(exc).__name__}: {exc}")
    if skipped_missing_key:
        print(
            "[WARN] provider factory creation skipped for providers without apiKey: "
            + ", ".join(skipped_missing_key),
            file=sys.stderr,
        )
    return errors


def _check_executable_scripts(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in ("Restart.sh", "build_and_run.sh", "scripts/acceptance_linux.sh"):
        path = root / relative
        if not path.exists():
            errors.append(f"missing executable script: {relative}")
            continue
        mode = path.stat().st_mode
        if not (mode & stat.S_IXUSR):
            errors.append(f"script is not executable: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentPark Linux acceptance contract checks.")
    parser.add_argument(
        "--skip-provider-factory",
        action="store_true",
        help="Skip create_agent checks for local provider entries.",
    )
    args = parser.parse_args()

    root = _repo_root()
    providers = _providers_from_config(root)
    errors: list[str] = []
    errors.extend(_check_json_files(root))
    errors.extend(_check_provider_types(providers))
    errors.extend(_check_loader_contract(root))
    errors.extend(_check_executable_scripts(root))
    if not args.skip_provider_factory:
        errors.extend(_check_provider_factory(root, providers))

    if errors:
        print("[FAIL] Linux acceptance contract checks failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("[OK] Linux acceptance contract checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
