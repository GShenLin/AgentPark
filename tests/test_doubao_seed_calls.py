import json

import pytest

from src.cli_provider_runtime.contracts import CodexProtocolError
from src.cli_provider_runtime.doubao_seed_parser import split_seed_calls
from src.cli_provider_runtime.doubao_seed_response import SeedResponseNormalizer
from src.cli_provider_runtime.doubao_seed_tools import SeedToolRegistry


COMMAND = r"Get-ChildItem -Path 'D:\Project\Dev_Intergration' | Select-Object Mode, Name"
FUNCTION = {
    "type": "function", "name": "exec_command",
    "parameters": {
        "type": "object", "properties": {"cmd": {"type": "string"}, "login": {"type": "boolean"}},
        "required": ["cmd"], "additionalProperties": False,
    },
}


def seed(body, name="exec_command"):
    return f'<seed:tool_call><function name="{name}">{body}</function></seed:tool_call>'


def response(text):
    return {"id": "resp_test", "status": "completed", "output_text": text, "output": [{
        "type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
        "phase": "final_answer", "content": [{"type": "output_text", "text": text}],
    }]}


@pytest.mark.parametrize("opening", [
    '<parameter name="cmd">', '<parameter name="cmd" string">',
    '<parameter name="cmd"> string">', '<parameter name="cmd" type="string">',
])
def test_observed_seed_dialects_preserve_command_bytes(opening):
    command = COMMAND + '\n& echo "$env:TEMP $(Get-Date) < > &amp; `"quoted`""'
    text, calls = split_seed_calls("我先检查。" + seed(opening + command + "</parameter>"))
    item = SeedToolRegistry({"tools": [FUNCTION]}).convert(calls[0])
    assert text == "我先检查。"
    assert item["type"] == "function_call"
    assert json.loads(item["arguments"]) == {"cmd": command}


def test_multiple_functions_in_one_seed_block_get_distinct_ids():
    functions = "".join(
        f'<function name="exec_command"><parameter name="cmd" string">{command}</parameter></function>'
        for command in [COMMAND, "Test-Path 'D:\\Project\\Dev_Intergration\\XYJ.uproject'"]
    )
    result = SeedResponseNormalizer(SeedToolRegistry({"tools": [FUNCTION]})).response(
        response("先确认路径。<seed:tool_call>" + functions + "</seed:tool_call>")
    )
    assert result["output_text"] == "先确认路径。"
    assert result["output"][0]["phase"] == "commentary"
    first, second = result["output"][1:]
    assert first["call_id"] != second["call_id"]
    assert json.loads(first["arguments"])["cmd"] == COMMAND


@pytest.mark.parametrize("wrapper", ["`{}`", "```xml\n{}\n```", "~~~xml\n{}\n~~~", "\\{}"])
def test_documented_or_escaped_seed_markup_stays_text(wrapper):
    text = wrapper.format(seed('<parameter name="cmd">echo example</parameter>'))
    assert split_seed_calls(text) == (text, ())


@pytest.mark.parametrize("text", [
    "<seed:tool_call>", "<seed:tool_call></seed:tool_call>",
    seed('<parameter name="cmd">unclosed'),
    seed('<parameter name="cmd">a</parameter><parameter name="cmd">b</parameter>'),
    seed('<parameter name="cmd" bogus="string">echo x</parameter>'),
    '<seed:tool_call><function name="exec_command"><parameter name="cmd">broken</function>'
    '<function name="exec_command"><parameter name="cmd">echo x</parameter></function></seed:tool_call>',
    seed('<parameter name="cmd">echo x</parameter>') + " unexpected suffix",
])
def test_invalid_seed_syntax_fails_explicitly(text):
    with pytest.raises(CodexProtocolError):
        split_seed_calls(text)


@pytest.mark.parametrize("body", [
    '', '<parameter name="cmd">echo x</parameter><parameter name="extra" string">x</parameter>',
    '<parameter name="cmd">echo x</parameter><parameter name="login" boolean">yes</parameter>',
    '<parameter name="cmd" number">123</parameter>',
])
def test_required_unknown_and_wrong_type_parameters_fail(body):
    _, calls = split_seed_calls(seed(body))
    with pytest.raises(CodexProtocolError):
        SeedToolRegistry({"tools": [FUNCTION]}).convert(calls[0])


def test_json_parameters_are_typed_and_validated():
    definition = {"type": "function", "name": "typed", "parameters": {
        "type": "object", "required": ["count", "items", "options", "enabled"],
        "properties": {"count": {"type": "integer", "minimum": 1}, "items": {"type": "array"},
                       "options": {"type": "object"}, "enabled": {"type": "boolean"}},
        "additionalProperties": False,
    }}
    body = ''.join(f'<parameter name="{key}">{value}</parameter>' for key, value in [
        ("count", "2"), ("items", '["a","b"]'), ("options", '{"path":"中文"}'), ("enabled", "false"),
    ])
    _, calls = split_seed_calls(seed(body, "typed"))
    item = SeedToolRegistry({"tools": [definition]}).convert(calls[0])
    assert json.loads(item["arguments"]) == {"count": 2, "items": ["a", "b"], "options": {"path": "中文"}, "enabled": False}


def test_string_ref_and_enum_schemas_do_not_require_redundant_type_hints():
    definition = {"type": "function", "name": "schema", "parameters": {
        "type": "object", "$defs": {"text": {"type": "string"}},
        "properties": {"path": {"$ref": "#/$defs/text"}, "mode": {"enum": ["read", "write"]}},
    }}
    _, calls = split_seed_calls(seed('<parameter name="path">D:\\中文</parameter><parameter name="mode">read</parameter>', "schema"))
    item = SeedToolRegistry({"tools": [definition]}).convert(calls[0])
    assert json.loads(item["arguments"]) == {"path": "D:\\中文", "mode": "read"}


def test_namespaces_and_additional_tools_are_resolved_from_request():
    registry = SeedToolRegistry({"input": [{"type": "additional_tools", "role": "developer", "tools": [
        {"type": "namespace", "name": "shell", "tools": [FUNCTION]},
    ]}]})
    _, calls = split_seed_calls(seed('<parameter name="cmd">echo x</parameter>', "shell.exec_command"))
    result = registry.convert(calls[0])
    assert result["namespace"] == "shell"
    assert result["name"] == "exec_command"


def test_ambiguous_and_undeclared_tools_are_not_guessed():
    registry = SeedToolRegistry({"tools": [
        {"type": "namespace", "name": name, "tools": [FUNCTION]} for name in ["a", "b"]
    ]})
    _, calls = split_seed_calls(seed('<parameter name="cmd">echo x</parameter>'))
    with pytest.raises(CodexProtocolError, match="ambiguous"):
        registry.convert(calls[0])
    with pytest.raises(CodexProtocolError, match="undeclared"):
        SeedToolRegistry({"tools": []}).convert(calls[0])


def exec_registry(nested="exec_command", **extra):
    return SeedToolRegistry({"tools": [{
        "type": "custom", "name": "exec", "format": {"type": "text"},
        "description": f"exec tool declaration:\n```ts\ndeclare const tools: {{ {nested}(args: {{ cmd: string; }}): Promise<unknown>; }};\n```",
    }], **extra})


@pytest.mark.parametrize("nested,argument", [("exec_command", "cmd"), ("shell_command", "command")])
def test_nested_shell_calls_use_codex_exec_with_json_escaped_arguments(nested, argument):
    cmd = COMMAND + '\nWrite-Output "` $() \\"; untrusted() //"'
    _, calls = split_seed_calls(seed(f'<parameter name="cmd">{cmd}</parameter>'))
    result = exec_registry(nested).convert(calls[0])
    assert result["type"] == "custom_tool_call"
    assert result["name"] == "exec"
    prefix = f"text(await tools.{nested}("
    assert result["input"].startswith(prefix)
    assert result["input"].endswith("));")
    assert json.loads(result["input"][len(prefix):-3]) == {argument: cmd}


def test_shell_contract_translation_does_not_drop_pty_arguments():
    _, calls = split_seed_calls(seed('<parameter name="cmd">echo x</parameter><parameter name="tty">true</parameter>'))
    with pytest.raises(CodexProtocolError, match="shell contract conversion"):
        exec_registry("shell_command").convert(calls[0])


def test_nested_shell_must_be_declared_and_tool_choice_is_respected():
    _, calls = split_seed_calls(seed('<parameter name="cmd">echo x</parameter>'))
    with pytest.raises(CodexProtocolError, match="does not declare"):
        exec_registry("unrelated").convert(calls[0])
    with pytest.raises(CodexProtocolError, match="tool_choice"):
        exec_registry(tool_choice="none").convert(calls[0])


def test_native_and_text_calls_are_not_both_executed():
    payload = response(seed('<parameter name="cmd">echo x</parameter>'))
    payload["output"].append({"type": "function_call", "name": "exec_command", "call_id": "native", "arguments": '{}'})
    with pytest.raises(CodexProtocolError, match="mixed"):
        SeedResponseNormalizer(SeedToolRegistry({"tools": [FUNCTION]})).response(payload)


def test_incomplete_response_never_promotes_text_to_calls():
    payload = {**response(seed('<parameter name="cmd">echo x</parameter>')), "status": "incomplete"}
    assert SeedResponseNormalizer(SeedToolRegistry({"tools": [FUNCTION]})).response(payload) == payload
