import json

from src.generation_output import ResourceOutputField, StructuredOutputSpec, build_generation_output_message


def test_generation_output_uses_text_fields_and_tailored_resources():
    payload = build_generation_output_message(
        {
            "response": "done",
            "saved_files": ["  file-a.glb  ", "", "file-b.glb"],
            "task_uuid": "task-1",
            "status": "success",
        },
        text_fields=("response",),
        resource_fields=(ResourceOutputField(name="saved_files", kind="file", source="model_generation", allow_list=True),),
        structured=StructuredOutputSpec(
            base={"provider_id": "hyper3d"},
            field_names=("task_uuid", "status"),
            count_field="saved_files",
            count_name="file_count",
        ),
        json_fallback="when_only_structured",
    )

    parts = payload["parts"]
    assert parts[0]["type"] == "text"
    assert parts[0]["text"] == "done"
    assert parts[1]["type"] == "resource"
    assert parts[1]["resource"]["uri"] == "file-a.glb"
    assert parts[2]["resource"]["uri"] == "file-b.glb"
    assert parts[-1]["type"] == "structured"
    assert parts[-1]["data"]["file_count"] == 3


def test_generation_output_falls_back_to_json_when_only_structured():
    payload = build_generation_output_message(
        {"task_id": "task-1"},
        text_fields=("response", "text"),
        structured=StructuredOutputSpec(base={"provider_id": "demo"}, field_names=("task_id",)),
        json_fallback="when_only_structured",
    )

    parts = payload["parts"]
    assert parts[0]["type"] == "text"
    assert json.loads(parts[0]["text"]) == {"task_id": "task-1"}
    assert parts[1]["type"] == "structured"
    assert parts[1]["data"] == {"provider_id": "demo", "task_id": "task-1"}


def test_generation_output_uses_no_parts_json_fallback():
    payload = build_generation_output_message(
        {"status": "ok"},
        text_fields=("response", "text"),
        structured=StructuredOutputSpec(field_names=("task_id",)),
        json_fallback="when_no_parts",
    )

    parts = payload["parts"]
    assert parts[0]["type"] == "text"
    assert json.loads(parts[0]["text"]) == {"status": "ok"}
