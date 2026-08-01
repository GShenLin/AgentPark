# AgentNode R30 冻结基线

日期：2026-07-25

## 决策

R30 固定为 AgentNode 当前默认长程任务基线。后续实验只有在同一冻结任务、同一
`GPT_Official` Provider、同一 `GPT1` Profile、同一 `system_tools` 工具包和同一外部
31 项 evaluator 下，综合结果明确优于 R30，才允许替换默认路径。

R30 的正式成绩：

| 指标 | R30 |
|---|---:|
| 墙钟耗时 | 746.671 s |
| 模型轮数 | 14 |
| 工具调用 | 13 |
| Runtime 失败 | 0 |
| Input tokens | 694,107 |
| Cached input | 621,824 |
| Output tokens | 31,004 |
| Total tokens | 725,111 |
| 非缓存输入 + Output | 103,287 |
| 外部验收 | 31/31 |

R32 的 Input/Total 更低，但耗时比 R30 慢 34.5%，模型轮数和工具调用也更多；因此它是
单项 Token 冠军，不是综合默认版本。R31、R33—R39 均未同时超过 R30 的速度、有效
Token、交互次数、失败率和正确性。

## 已恢复的 R30 行为契约

- `agent/GPT1.json` 使用 `GPT_Official`，仅加载 `system_tools`，不加载 plugin、skill
  或 MCP server。
- 直接 `apply_patch` 只要求 `patch`；R31 新增的直接调用 `required_changes` 强制合同
  已撤销。`workspace_exec` 内部的结构化补丁后置条件仍保留。
- `workspace_exec` 顶层只接受 `stages`；R34 的 `context_checkpoint` 生命周期字段及其
  提示词已撤销。
- R32—R34 的 completed-tool checkpoint、receipt chain 和 lifecycle policy 已从运行时
  移除。
- R36—R37 的 Agent 客户端稳定 `prompt_cache_key`、诊断字段和基准采集字段已移除。
- `GPT_Official` 不再启用 `responsesCompletedToolCheckpointEnabled`。

## 保留范围

这不是把整个仓库回退到 2026-07-24 的时间快照。R30 当时没有独立 Git commit，且后续
提交混合了 Codex/Claude 节点、UI 和其他无关产品改动。本次只恢复有 R30 实测线协议证据
的 AgentNode 默认行为，并保留无关产品代码。

回退前工作区已保存在 Git stash：

```text
pre-r30-agent-behavior-rollback-2026-07-25
```

## 自动化护栏

`tests/test_r30_agent_baseline.py` 固定以下约束：

1. GPT1 = GPT_Official + 单一 system_tools；
2. 直接 apply_patch 不含 required_changes；
3. workspace_exec 顶层只有 stages；
4. GPT_Official 默认请求不含客户端 prompt_cache_key；
5. completed-tool checkpoint 配置不存在。

任何后续版本若要改变这些默认值，必须先以正式长程 benchmark 证明综合超过 R30。

## 回退验证

- R30/Responses 聚焦回归：164 passed。
- 最终核心回归：86 passed。
- 全仓回归：1654 passed、4 skipped、3 failed。
- 3 个全仓失败均不在本次修改文件中：DeepSeek Tavern 配置模型名与既有测试不一致；
  另外两个 Windows 时序测试单独复现时通过。它们未被改断言或静默忽略。
