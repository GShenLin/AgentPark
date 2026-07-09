from __future__ import annotations

from src.name_lists import NameListContract


NODE_CAPABILITY_LIST = NameListContract(
    list_label="node capabilities",
    item_label="capability names",
    error_type=None,
    accepted_types=(list, tuple),
)


__all__ = ["NODE_CAPABILITY_LIST"]
