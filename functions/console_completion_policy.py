import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ConsoleCommandProfile:
    blocked: bool = False
    block_error: str = ""
    hint: str = ""
    minimum_timeout_seconds: int | None = None
    completion_kind: str = ""


def classify_console_command(command) -> ConsoleCommandProfile:
    command_lower = str(command or "").lower()

    if _looks_like_high_context_git_diff(command_lower):
        return ConsoleCommandProfile(
            blocked=True,
            block_error="High-context git diff commands are blocked because they can produce output and still time out.",
            hint="Use 'git --no-pager diff --stat', '--numstat', '--name-only', or read narrow changed regions directly.",
        )

    if (
        "npx" in command_lower
        and "skills" in command_lower
        and "find" in command_lower
        and "--yes" not in command_lower
        and "npx -y" not in command_lower
    ):
        return ConsoleCommandProfile(
            blocked=True,
            block_error="Interactive npx skill discovery is blocked because it can wait for package-install confirmation.",
            hint="Use 'npx --yes skills find ...' or 'npx -y skills find ...'.",
        )

    if _looks_like_broad_powershell_file_scan(command_lower):
        return ConsoleCommandProfile(
            blocked=True,
            block_error="Broad recursive PowerShell file scans are blocked because they repeatedly time out in this workspace.",
            hint="Use rg_search_text for text search or rg_list_files for focused inventories.",
        )

    if _looks_like_webui_build(command_lower):
        return ConsoleCommandProfile(minimum_timeout_seconds=540, completion_kind="webui_build")
    if _looks_like_pytest_collect(command_lower):
        return ConsoleCommandProfile(minimum_timeout_seconds=180, completion_kind="pytest_collect")
    if _looks_like_pytest_run(command_lower):
        return ConsoleCommandProfile(minimum_timeout_seconds=300, completion_kind="pytest")
    return ConsoleCommandProfile()


def analyze_console_completion(
    stdout: str,
    stderr: str,
    status: str,
    profile: ConsoleCommandProfile,
) -> tuple[str, str | None, dict]:
    extra: dict = {}
    final_status = status
    error = None
    combined_lower = f"{stdout or ''}\n{stderr or ''}".lower()

    if profile.completion_kind == "webui_build":
        completed = bool(
            re.search(r"\bbuilt in\s+\d", combined_lower)
            or "vite" in combined_lower
            and "built in" in combined_lower
        )
        extra["detected_completion"] = {"kind": "webui_build", "completed": completed}
        if status == "timeout" and completed:
            final_status = "partial_success_timeout"
            error = "Command timed out after output that matches a completed WebUI build."

    elif profile.completion_kind == "pytest_collect":
        match = re.search(r"(\d+)\s+tests?\s+collected", combined_lower)
        details = {"kind": "pytest_collect", "completed": match is not None}
        if match:
            details["collected_tests"] = int(match.group(1))
        extra["detected_completion"] = details
        if status == "timeout" and match is not None:
            final_status = "partial_success_timeout"
            error = "Command timed out after pytest reported completed collection."

    elif profile.completion_kind == "pytest":
        failure_counts = [
            int(match.group(1))
            for match in re.finditer(r"\b(\d+)\s+(?:failed|errors?)\b", combined_lower)
        ]
        failed_tests = max(failure_counts, default=0)
        completed = bool(
            failed_tests
            or re.search(r"\b\d+\s+(?:passed|skipped|xfailed|xpassed)\b", combined_lower)
        )
        extra["detected_completion"] = {
            "kind": "pytest",
            "completed": completed,
            "failed_tests": failed_tests,
        }
        if failed_tests:
            final_status = "error"
            error = (
                f"Pytest reported {failed_tests} failed/error tests"
                + (" despite a zero process return code." if status == "success" else ".")
            )

    return final_status, error, extra


def _looks_like_high_context_git_diff(command_lower: str) -> bool:
    if "git" not in command_lower or "diff" not in command_lower:
        return False
    for match in re.finditer(r"--unified[=\s]+(\d+)|-u\s*(\d+)", command_lower):
        value = match.group(1) or match.group(2)
        try:
            if int(value) > 20:
                return True
        except Exception:
            continue
    return False


def _looks_like_broad_powershell_file_scan(command_lower: str) -> bool:
    has_recursive_ps_listing = (
        ("get-childitem" in command_lower or re.search(r"(^|\W)gci(\W|$)", command_lower))
        and "-recurse" in command_lower
    )
    has_content_line_count = "measure-object" in command_lower and "get-content" in command_lower
    has_rg_file_content_count = bool(
        "measure-object" in command_lower
        and "get-content" in command_lower
        and re.search(r"\brg(\.exe)?\s+--files\b", command_lower)
    )
    return bool((has_recursive_ps_listing and has_content_line_count) or has_rg_file_content_count)


def _looks_like_webui_build(command_lower: str) -> bool:
    return "npm" in command_lower and "run" in command_lower and "build" in command_lower


def _looks_like_pytest_collect(command_lower: str) -> bool:
    return "pytest" in command_lower and "--collect-only" in command_lower


def _looks_like_pytest_run(command_lower: str) -> bool:
    return "pytest" in command_lower
