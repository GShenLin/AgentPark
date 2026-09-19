from __future__ import annotations

from .contracts import encode
from .retrieval import MemoryReader


def install_tools(agent, reader: MemoryReader) -> None:
    """Bind capabilities to a host-selected store, never a model-supplied path/node id."""
    def search_node_memory(query: str, limit: int = 10):
        return encode(reader.search(query, limit))

    def read_node_memory(source_id: str, offset: int = 0, limit: int = 6000, evidence: bool = False):
        return encode(reader.read(source_id, offset, limit, evidence))

    def add_node_memory_note(content: str):
        return encode({"note_id": reader.store.add_note(content), "status": "pending_consolidation"})

    def forget_node_memory(source_id: str):
        reader.read(source_id)  # Validate the exact node-local id before changing state.
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
    for function, description, properties, required in declarations:
        agent.tools.register_external_tool({"type": "function", "function": {
            "name": function.__name__, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required, "additionalProperties": False},
        }}, function)
