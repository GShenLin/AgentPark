from __future__ import annotations

from .contracts import encode
from .retrieval import MemoryReader


def _reader(agent) -> MemoryReader:
    reader = getattr(agent, "_agentpark_memory_reader", None)
    if not isinstance(reader, MemoryReader):
        raise ValueError("Node memory is not enabled or bound for this Agent.")
    return reader


def search_node_memory(query: str, limit: int = 10, agent=None):
    return encode(_reader(agent).search(query, limit))


def read_node_memory(source_id: str, offset: int = 0, limit: int = 6000, evidence: bool = False, agent=None):
    return encode(_reader(agent).read(source_id, offset, limit, evidence))


def add_node_memory_note(content: str, agent=None):
    return encode({"note_id": _reader(agent).store.add_note(content), "status": "pending_consolidation"})


def forget_node_memory(source_id: str, agent=None):
    reader = _reader(agent)
    reader.read(source_id)
    reader.store.forget_source(source_id)
    return encode({"status": "forgotten", "source_id": source_id})


declarations = [
    (forget_node_memory, "Only on an explicit user request to forget: exclude this exact source from future node memory. Original chat history remains.",
     {"source_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}, ["source_id"]),
    (search_node_memory, "Search this node's extracted historical memories for a literal phrase. No cross-node access.",
     {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
    (read_node_memory, "Read a memory by exact 64-character hex source id, WITHOUT the memory: prefix. Copy the complete id; do not abbreviate. Set evidence=true for original source records; paginate with next_offset.",
     {"source_id": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
      "limit": {"type": "integer", "minimum": 1, "maximum": 12000}, "evidence": {"type": "boolean"}}, ["source_id"]),
    (add_node_memory_note, "Only on an explicit user request to remember or correct: submit a node-local memory edit for consolidation.",
     {"content": {"type": "string"}}, ["content"]),
]

TOOL_BINDINGS = tuple(({
    "type": "function", "function": {
        "name": function.__name__, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False},
    },
}, function) for function, description, properties, required in declarations)

forget_node_memory_declaration, search_node_memory_declaration, read_node_memory_declaration, add_node_memory_note_declaration = (
    declaration for declaration, _ in TOOL_BINDINGS
)


def install_tools(agent, reader: MemoryReader) -> None:
    """Explicit installation for callers that opt in; normal nodes use the memory Skill."""
    agent._agentpark_memory_reader = reader
    for declaration, function in TOOL_BINDINGS:
        agent.tools.register_external_tool(declaration, function)
