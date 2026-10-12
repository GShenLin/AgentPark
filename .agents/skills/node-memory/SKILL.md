---
name: node-memory
description: 查询当前节点的历史记忆和原始依据，或按用户要求记住、更正、遗忘信息。
---

调用 `activate_skill("node-memory")` 后，当前轮会提供四个节点记忆工具。

- 用 `search_node_memory` 搜索相关历史，用 `read_node_memory` 读取完整的 64 位 source_id（去掉 `memory:` 前缀）；需要原始依据时传 `evidence=true`，按 `next_offset` 分页。
- 只有用户明确要求记住或更正信息时，才用 `add_node_memory_note` 提交内容，后台会整理入记忆。
- 用户明确要求遗忘时，用 `forget_node_memory` 排除对应的完整 source_id；原聊天记录保留。

记忆是历史依据，当前指令优先；区分已验证结果、尝试和过期信息，重要结论注明来源。工具只访问宿主绑定的当前节点，不能指定其他节点或存储路径。
