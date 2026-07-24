import json
import textwrap

import pytest

from nodes.agent_skill_loader import SkillLoadError, load_node_skills, render_skill_instructions
from nodes.agent_skill_scripts import register_skill_script_tools
from src.tool.base_tool import BaseTool


class _Agent:
    def __init__(self):
        self.config = {}
        self.tools = BaseTool(self)


def _write_skill(root, *, manifest=None, scripts=None):
    skill_dir = root / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\n\nUse this skill.\n",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    for name, body in (scripts or {}).items():
        (scripts_dir / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    if manifest is not None:
        (skill_dir / "skill.json").write_text(json.dumps(manifest), encoding="utf-8")
    return skill_dir


def _script_manifest(script_id, entry, *, timeout=5, schema=None, allow_write=False, enabled=None):
    payload = {
        "id": script_id,
        "name": script_id.title(),
        "description": f"Run {script_id}.",
        "entry": entry,
        "argsSchema": schema
        or {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "cwd": ".",
        "timeoutSeconds": timeout,
        "allowWrite": allow_write,
    }
    if enabled is not None:
        payload["enabled"] = enabled
    return payload


def test_declared_readonly_skill_script_registers_and_executes(tmp_path):
    _write_skill(
        tmp_path,
        manifest={
            "scripts": [
                _script_manifest(
                    "echo",
                    "scripts/echo.py",
                    schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                )
            ]
        },
        scripts={
            "echo.py": """
                import json
                import sys

                payload = json.loads(sys.stdin.read())
                print(json.dumps({"echo": payload["text"]}))
            """
        },
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()

    registered = register_skill_script_tools(agent, skills)
    result = json.loads(agent.tools.function_map["skill__demo__echo"](text="hello"))

    assert registered == ["skill__demo__echo"]
    assert [item["function"]["name"] for item in agent.tools.tool_declarations] == ["skill__demo__echo"]
    assert result["status"] == "success"
    assert json.loads(result["stdout"]) == {"echo": "hello"}
    registered_callable = agent.tools.function_map["skill__demo__echo"]
    assert registered_callable.tool_timeout_seconds == 5


def test_skill_script_receives_node_directory(tmp_path):
    _write_skill(
        tmp_path,
        manifest={"scripts": [_script_manifest("where", "scripts/where.py")]},
        scripts={
            "where.py": """
                import os
                print(os.environ.get("AGENTPARK_NODE_DIRECTORY", ""))
            """
        },
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()
    agent._agentpark_node_directory = str(tmp_path)
    register_skill_script_tools(agent, skills)

    result = json.loads(agent.tools.function_map["skill__demo__where"]())

    assert result["stdout"].strip() == str(tmp_path)


def test_undeclared_script_resource_is_not_registered(tmp_path):
    _write_skill(
        tmp_path,
        manifest={"scripts": []},
        scripts={"hidden.py": "print('must not run')\n"},
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()

    registered = register_skill_script_tools(agent, skills)

    assert registered == []
    assert agent.tools.tool_declarations == []


def test_write_capable_skill_script_requires_explicit_enabled_switch(tmp_path):
    _write_skill(
        tmp_path,
        manifest={"scripts": [_script_manifest("write_it", "scripts/write_it.py", allow_write=True)]},
        scripts={"write_it.py": "print('write')\n"},
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()

    assert skills[0].script_tools[0].allow_write is True
    assert skills[0].script_tools[0].enabled is False
    assert register_skill_script_tools(agent, skills) == []


def test_invalid_script_arguments_return_typed_error_without_running_process(tmp_path):
    _write_skill(
        tmp_path,
        manifest={
            "scripts": [
                _script_manifest(
                    "needs_text",
                    "scripts/needs_text.py",
                    schema={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                )
            ]
        },
        scripts={"needs_text.py": "raise SystemExit('process should not run')\n"},
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()
    register_skill_script_tools(agent, skills)

    result = json.loads(agent.tools.function_map["skill__demo__needs_text"]())

    assert result["status"] == "error"
    assert result["exception_type"] == "SkillScriptArgumentError"
    assert "missing required script argument" in result["error"]


def test_skill_script_nonzero_exit_preserves_stdout_and_stderr(tmp_path):
    _write_skill(
        tmp_path,
        manifest={"scripts": [_script_manifest("fail", "scripts/fail.py")]},
        scripts={
            "fail.py": """
                import sys

                print("visible stdout")
                print("visible stderr", file=sys.stderr)
                raise SystemExit(7)
            """
        },
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()
    register_skill_script_tools(agent, skills)

    result = json.loads(agent.tools.function_map["skill__demo__fail"]())

    assert result["status"] == "error"
    assert result["exit_code"] == 7
    assert "visible stdout" in result["stdout"]
    assert "visible stderr" in result["stderr"]


def test_skill_script_timeout_is_visible_to_model(tmp_path):
    _write_skill(
        tmp_path,
        manifest={"scripts": [_script_manifest("slow", "scripts/slow.py", timeout=1)]},
        scripts={
            "slow.py": """
                import time

                print("started", flush=True)
                time.sleep(5)
            """
        },
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))
    agent = _Agent()
    register_skill_script_tools(agent, skills)

    result = json.loads(agent.tools.function_map["skill__demo__slow"]())

    assert result["status"] == "timeout"
    assert result["timed_out"] is True
    assert "started" in result["stdout"]


def test_invalid_skill_script_manifest_fails_skill_load(tmp_path):
    _write_skill(
        tmp_path,
        manifest={
            "scripts": [
                {
                    "id": "bad",
                    "entry": "../bad.py",
                    "argsSchema": {"type": "object"},
                    "cwd": ".",
                    "timeoutSeconds": 5,
                    "allowWrite": False,
                }
            ]
        },
        scripts={},
    )

    with pytest.raises(SkillLoadError) as exc:
        load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))

    assert "must not contain . or .." in str(exc.value)


def test_skill_prompt_lists_script_metadata_not_script_source(tmp_path):
    _write_skill(
        tmp_path,
        manifest={"scripts": [_script_manifest("echo", "scripts/echo.py")]},
        scripts={"echo.py": "SECRET_SCRIPT_BODY = True\nprint('ok')\n"},
    )
    skills = load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path))

    rendered = render_skill_instructions(skills)

    assert "<script_tools>" in rendered
    assert "<id>echo</id>" in rendered
    assert "SECRET_SCRIPT_BODY" not in rendered
