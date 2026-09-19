from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.peer_network.contracts import PeerCall, PeerGrant
from src.peer_network.delivery import DeliveryJournal
from src.web_backend.peer_operations import PeerOperations


@pytest.fixture
def operations(tmp_path):
    core = SimpleNamespace(
        graph_api=SimpleNamespace(
            list_graphs=Mock(return_value={"graphs": [{"id": "shared", "name": "Shared"}, {"id": "other", "name": "Other"}]}),
            require_graph_visible=Mock(),
        ),
        mobile_api=SimpleNamespace(list_mobile_nodes=Mock(return_value={"nodes": [
            {"id": "agent", "name": "Agent", "state": "idle", "workspace_path": "private-path"}]})),
        node_ops=SimpleNamespace(
            require_node_visible=Mock(),
            get_node_instance_memory=Mock(return_value={"text": "hello", "messages": [], "state": "idle",
                                                        "history_complete": False, "live_message": "", "memory_path": "private-path"}),
            enqueue_node_instance_pending=Mock(return_value={"duplicate": False, "pending_count": 1}),
            control_node_instance=Mock(return_value={"ok": True}),
        ),
    )
    return PeerOperations(core, DeliveryJournal(tmp_path / "deliveries.db"))


def grant(**flags):
    return PeerGrant(peer_id="a" * 64, name="Other", graph_ids=["shared"], **flags)


def test_read_scope_filters_graphs_and_runtime_paths(operations):
    assert operations.execute(grant(view=True), PeerCall(operation="graphs")) == {
        "graphs": [{"id": "shared", "name": "Shared"}]}
    result = operations.execute(grant(view=True), PeerCall(operation="nodes", graph_id="shared"))
    assert "workspace_path" not in result["nodes"][0]
    result = operations.execute(grant(view=True), PeerCall(operation="conversation", graph_id="shared", node_id="agent"))
    assert "memory_path" not in result
    with pytest.raises(PermissionError):
        operations.execute(grant(view=True), PeerCall(operation="nodes", graph_id="other"))


@pytest.mark.parametrize("operation,flag", [("graphs", "control"), ("message", "view"), ("agent_message", "control"), ("control", "collaborate")])
def test_view_control_and_collaboration_permissions_are_independent(operations, operation, flag):
    with pytest.raises(PermissionError):
        operations.execute(grant(**{flag: True}), PeerCall(operation=operation, graph_id="shared", node_id="agent"))
    operations.core.node_ops.enqueue_node_instance_pending.assert_not_called()
    operations.core.node_ops.control_node_instance.assert_not_called()


def test_agent_delivery_is_attributed_and_receipt_does_not_claim_completion(operations):
    call = PeerCall(operation="agent_message", graph_id="shared", node_id="agent", source_graph_id="source",
                    source_node_id="sender", text="Please review the change", message_id="request-001")
    result = operations.execute(grant(collaborate=True), call)
    assert result["queued"] and not result["completed"]
    assert result["source"]["peer_id"] == "a" * 64
    args, kwargs = operations.core.node_ops.enqueue_node_instance_pending.call_args
    assert "source/sender" in args[1]["payload"]["content"]
    assert kwargs["request"].client.host != "127.0.0.1"
    assert kwargs["request"].state.peer_principal.peer_id == "a" * 64
    assert operations.execute(grant(collaborate=True), call)["duplicate"]
    assert operations.core.node_ops.enqueue_node_instance_pending.call_count == 1


def test_private_node_denial_is_preserved(operations):
    operations.core.node_ops.require_node_visible.side_effect = HTTPException(404, "private node")
    with pytest.raises(HTTPException):
        operations.execute(grant(control=True), PeerCall(operation="message", graph_id="shared", node_id="private", text="x", message_id="x"))
    operations.core.node_ops.enqueue_node_instance_pending.assert_not_called()
