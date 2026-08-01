from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _board_source() -> str:
    return (ROOT / "webui/src/components/agent-board/useAgentBoard.ts").read_text(encoding="utf-8")


def test_copied_node_paste_selects_and_focuses_the_new_nodes():
    source = _board_source()
    apply_paste = source.split("async function applyPastePlanToBoard", 1)[1].split(
        "async function selectAndFocusPastedNodes", 1
    )[0]

    assert "nodes.value.push(...plan.nodes)" in apply_paste
    assert "await selectAndFocusPastedNodes(plan.nodes.map((node) => node.id))" in apply_paste


def test_text_and_image_paste_focuses_paste_agent_before_sending_content():
    source = _board_source()
    paste_agent = source.split("async function pasteClipboardContentAsAgent", 1)[1].split(
        "function nodeWorkingPath", 1
    )[0]

    focus_call = "await selectAndFocusPastedNodes([nodeId])"
    send_call = "await sendNodeMessage(nodeId, message)"
    assert focus_call in paste_agent
    assert send_call in paste_agent
    assert paste_agent.index(focus_call) < paste_agent.index(send_call)


def test_paste_focus_preserves_multi_node_selection_and_centers_the_first_node():
    source = _board_source()
    helper = source.split("async function selectAndFocusPastedNodes", 1)[1].split(
        "async function ensurePasteAgentConfigLoaded", 1
    )[0]

    assert "selectedItemIds.value = pastedNodeIds" in helper
    assert "if (pastedNodeIds.length === 1)" in helper
    assert "selectNode(pastedNodeIds[0]!)" in helper
    assert "return focusNodeInViewport(pastedNodeIds[0]!)" in helper
