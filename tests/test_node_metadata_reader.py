import os

import pytest

from src.web_backend.node_metadata_reader import (
    NodeCreateError,
    NodeMetadataReadError,
    NodeMetadataSignatureError,
    NodeModuleLoadError,
    load_node_instance,
    read_node_ports,
    read_node_schema,
    run_node_on_create,
)


def _write_node(nodes_dir, type_id: str, source: str) -> None:
    path = os.path.join(nodes_dir, f"{type_id}.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)


def test_load_node_instance_missing_file_returns_none(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: str(nodes_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_resource_root", lambda: str(tmp_path))

    assert load_node_instance("missing_node") is None


def test_load_node_instance_import_error_raises_module_error(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    _write_node(nodes_dir, "broken_node", "raise RuntimeError('boom')\n")
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: str(nodes_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_resource_root", lambda: str(tmp_path))

    with pytest.raises(NodeModuleLoadError, match="broken_node"):
        load_node_instance("broken_node")


def test_read_node_ports_passes_context_to_context_aware_getters():
    class Node:
        def getInputNum(self, context):
            return context["inputs"]

        def getOutputNum(self, context):
            return context["outputs"]

    assert read_node_ports(Node(), {"inputs": "2", "outputs": "3"}) == (2, 3)


def test_read_node_ports_supports_no_arg_getters():
    class Node:
        def getInputNum(self):
            return 4

        def getOutputNum(self):
            return 5

    assert read_node_ports(Node(), {"ignored": True}) == (4, 5)


def test_internal_type_error_from_port_getter_is_not_retried_as_no_arg_fallback():
    calls = []

    class Node:
        def getInputNum(self, context=None):
            calls.append(context)
            raise TypeError("internal port bug")

        def getOutputNum(self, context=None):
            return 1

    with pytest.raises(NodeMetadataReadError, match="internal port bug"):
        read_node_ports(Node(), {"x": 1})
    assert calls == [{"x": 1}]


def test_invalid_port_getter_signature_raises_signature_error():
    class Node:
        def getInputNum(self, first, second):
            return 1

        def getOutputNum(self):
            return 1

    with pytest.raises(NodeMetadataSignatureError, match="getInputNum"):
        read_node_ports(Node(), {})


def test_get_config_schema_exception_raises_metadata_read_error():
    class Node:
        def get_config_schema(self, context):
            raise ValueError("schema broke")

    with pytest.raises(NodeMetadataReadError, match="schema broke"):
        read_node_schema(Node(), {})


def test_on_create_exception_raises_node_create_error():
    class Node:
        def on_create(self, config, context):
            raise RuntimeError("create broke")

    with pytest.raises(NodeCreateError, match="create broke"):
        run_node_on_create(Node(), {}, {})
