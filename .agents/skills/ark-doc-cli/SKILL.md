---
name: ark-doc-cli
description: 方舟文档 CLI 工具的安装、升级与使用指南。当用户需要搜索火山方舟文档、查询模型信息、获取 API 规范、查找代码示例或管理方舟 Skill 时调用。
version: 0.1.0
author: Ark Doc Team
---

# ark-doc：火山方舟文档工具

本节点已配置 **Ark Docs MCP**。优先直接调用该 MCP 提供的工具，不要为了完成普通查询而安装额外 CLI：

- `ark_search_docs`：搜索火山方舟文档。
- `ark_list_docs` / `ark_fetch_doc`：列出和读取文档。
- `ark_list_models` / `ark_get_model`：查询模型能力和详情。
- `ark_list_apis` / `ark_get_spec`：查询 API 列表和规范。
- `ark_search_examples`：搜索代码示例。
- `ark_list_skills` / `ark_get_skill`：发现和获取方舟 Skill。

## 工作规则

1. 先使用最窄的查询参数，避免一次拉取过多内容。
2. 搜索文档后，只读取与问题直接相关的文档分块。
3. 查询模型时，根据用户要求组合领域、厂商、深度思考、工具调用、MCP、价格或限流条件。
4. 查询 API 时，先列出或确定准确路径，再获取对应规范。
5. 安装其他 Skill 前，先调用 `ark_list_skills`，再用准确的 `skill_id` 调用 `ark_get_skill`；不要猜测下载地址或版本。
6. 对实时返回的模型、文档、API 和 Skill 信息，明确其来自火山方舟服务。

## 可选 CLI

仅当用户明确要求在终端使用 `ark-doc` 时，才安装或运行方舟文档 CLI。CLI 支持文档搜索、模型查询、API 规范、代码示例、Skill 管理和连接诊断，并可通过 `ARK_MCP_URL` 指定 MCP 服务地址。
