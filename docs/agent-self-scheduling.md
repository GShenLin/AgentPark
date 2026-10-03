# Agent 自主唤醒调度

图中的 `agent_node` 现在可以通过 `system_tools` 中的 `manage_agent_schedule` 自行创建、查询、更新和取消后续唤醒，无需手工添加 Clock 节点。也可单独加载 `agent_schedule_tools` 工具包。独立运行、没有图后端绑定的 Agent 会收到明确错误。

## 工具用法

一次性延时：

```json
{"action":"create","prompt":"检查刚才启动的构建是否完成，继续原任务","delay_seconds":300,"idempotency_key":"check-build-1"}
```

固定间隔重复：

```json
{"action":"create","prompt":"检查服务状态并按原任务要求处理","run_at":"2026-10-04T09:00:00+08:00","interval_seconds":3600,"idempotency_key":"service-check"}
```

- `run_at` 和 `delay_seconds` 必须且只能提供一个
- 绝对时间必须包含 UTC `Z` 或明确偏移量；返回的时间统一为 UTC
- 重复周期至少 60 秒，按固定秒数计算，不是本地日历/夏令时 cron
- 同一任务中重试创建时复用 `idempotency_key`；相同 key、不同参数会报错
- 工具结果为 `{"status":"success","result":...}`；失败为 `status=error`
- `list` 返回当前节点的全部调度；`get` 加 `schedule_id` 查询单个调度
- `update` / `cancel` 需要 `schedule_id` 和最近查询得到的 `expected_revision`
- 更新省略的字段保持不变；`interval_seconds:null` 取消重复；新时间必须在未来
- 取消阻止未来及尚未开始的唤醒，不能撤销已经开始的 Agent 工作

## 上下文和权限

调度目标、原任务 ID 和访问元数据由后端绑定，工具不接受任意目标节点/图/目录。唤醒使用原节点、原任务 ID、该节点配置的会话历史和持久化任务方向记录。每次投递拥有独立 trace ID。不会保存进程栈或完整 Python 执行现场，唤醒提示应写清下一步；共享节点历史仍遵循现有节点历史策略。

默认非开发者工具过滤器同时过滤独立调度工具包及 `system_tools`，既有访问过滤策略保持生效。调度记录在同节点内可被后续任务查询和取消，但不能读取/修改其他节点的调度。

## 执行与恢复语义

- SQLite 调度与 outbox 保存在当前 memories 根目录下的 `agent-schedules.sqlite3`
- 复用已有定时线程和图执行器，约 1 秒轮询 outbox，不为每项调度创建线程
- 每个调度最多一个未完成投递；节点由现有执行器串行执行，不打断当前 turn
- 错过的重复周期合并为一次唤醒，下一时间按原周期推算，避免离线后积压风暴
- 节点停止时暂停投递，节点恢复后再唤醒；节点不存在或类型不匹配时投递失败
- 队列本身仍是内存状态；SQLite outbox 直到执行结束且输出持久化后才确认
- 启动恢复会重新排队尚未确认的唤醒，时间已过的一次性调度也会补发
- 崩溃恢复是“至少一次”：如果外部副作用已发生但尚未确认，重启可能重放。重要操作应自己使用幂等键，不能依赖 exactly-once 保证
- 明确的执行错误记为失败，不无限重试该次唤醒；重复调度的后续周期仍正常运行
- 需要 AgentPark 后端持续运行才能按时唤醒；进程关闭期间不能唤醒操作系统，重新启动后补发
- 同一 memories 目录应只运行一个后端实例；运行中记录的恢复发生在应用启动阶段

已有 Clock 节点行为不变；它的原有运行时倒计时并未因此变为持久化。

`status` 描述调度本身是否仍有后续触发时间；一次性调度生成投递后会变为 `completed`。执行进度请看 `last_delivery_status`（`pending` / `running` / `completed` / `failed` / `cancelled`），不要把调度时间耗尽误认为工作已成功完成。
