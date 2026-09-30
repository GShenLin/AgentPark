# 命令输出与进程会话

自有 Agent 的 `system_tools` 提供同步短命令和异步进程会话。两条路径共用 shell 启动契约。

## Shell 契约

- Windows 使用环境声明的 PowerShell，非交互、UTF-8 输入/输出；命令在临时 UTF-8 BOM 脚本中执行，外层刷新对象格式化输出后再退出。脚本文件在进程结束后删除。
- 默认 PowerShell cmdlet 错误终止执行；`throw`、原生非零退出码、显式 `exit N` 都返回失败，并保留已有输出。原生命令后跟成功 cmdlet 不会抹掉最后的原生失败码。若非零为预期结果，调用方应检查 `$LASTEXITCODE` 后明确 `exit 0`；wrapper 不推断哪些失败可忽略。
- 多个原生命令按最后的原生退出码处理；要对每条失败立即停止，应在命令中显式检查。PowerShell 的原生参数引用规则保持不变。
- POSIX 使用环境声明的 shell，其退出语义不变。所有平台输出都必须是 UTF-8；不猜编码、不替换损坏字节。

## 模型接口

| 接口 | 用途 |
|---|---|
| `execute_console_command(command, timeout_seconds, ...)` | 同步短命令，保留原有输出大小限制和测试完成判定 |
| `start_console_session(command, timeout_seconds=120, child_process_policy="error")` | 立即返回 session_id、PID、cwd、初始游标；执行总时限 0–3600 秒，0 禁用 |
| `read_console_session(session_id, cursor=null, max_chars=8000)` | 不等待，读取当前输出和状态 |
| `wait_console_session(session_id, cursor=null, wait_seconds=10, max_chars=8000)` | 最多等待 0–60 秒后读取；等待到期不终止命令 |
| `stop_console_session(session_id, cursor=null, max_chars=8000)` | 终止会话及其子进程，等待清理后返回结果 |

构建、测试、编辑器任务优先用会话。命令内直接以前台方式运行可执行文件，不要用后台操作脱离会话。Windows GUI 程序需显式等待：将调用接入 `Out-Default` 管道，或使用 `Start-Process -Wait -PassThru` 并把其 `ExitCode` 作为命令退出码。Windows shell 结束时若仍有活跃子进程，会话明确返回 error 并清理它们；不把提前退出误报成程序执行成功。会话不提供交互式 stdin。

`status` 为 running / success / error / timeout / stopped。`finished` 表示执行生命周期结束；`returncode` 是真实 shell 退出码，运行中为 null。执行结束后仍可能有未读输出，应继续读取到 `has_more_output=false`。会话的 success 只证明退出码为零、输出捕获完成，不能代替解析测试断言报告。

Windows 若前台程序本身已退出，但设计上留下了辅助进程（例如编辑器的崩溃监视器），调用者可显式选择 `child_process_policy="terminate"`。此时会话清理后代并按 shell 退出码判定，结果用 `terminated_children_on_shell_exit` 明确报告清理数量。默认 error 不变；不按进程名猜测哪些辅助进程可以忽略，也不应用自动重试降级。terminate 不能用于推断异步 GUI 程序的执行成功；必须另外验证目标程序报告。POSIX 暂不提供这项 Windows Job 计数策略。

游标包含 `{session_id, stdout, stderr}`，偏移按 Unicode 字符计算。传入上次 `next_cursor` 续读；不传从头回放。读取无副作用，同一个游标可以重试或并发读取，不能跨会话使用。每次最多返回 65,536 字符/流；Provider 提交上限可能缩小单页，但游标只推进实际返回字符，不会跳过未读输出。

输出在磁盘分流保留，跨数据块 UTF-8 字符由增量解码器处理。单流上限 16 Mi 字符；超过上限明确报错并停止命令，不静默丢弃。单个 Agent 运行最多 8 个运行中会话、128 个保留会话。

## 生命周期与边界

会话归创建它的 Agent 运行所有；其他 Agent 无法读取或停止它。节点 Stop、执行期限、显式停止，以及 Agent 正常结束或抛异常，都会清理运行中的会话。完成会话的输出保留到当前 Agent 运行结束，之后删除，不支持跨轮次或重启恢复。

Windows 先挂起创建 shell，把它放入 kill-on-close Job Object 后恢复，保证其后代归属同一进程树；进程结束或停止时关闭 Job。POSIX 使用独立进程组并清理组内后代。工具不支持进程主动脱离所属 Job / 进程组。

本版会话仅用于本地执行。远程节点调用会得到明确的不支持错误，不会在控制端偷偷执行远程命令；原同步远程命令不受影响。

## 验证

`tests/test_console_windows_output.py` 覆盖真实 PowerShell 对象/字符串混合输出、中文、显式退出、原生退出码、异常及脚本清理。

`tests/test_console_sessions.py` 覆盖实时输出、UTF-8 跨块、游标回放/分页/隔离、等待与执行超时区别、子进程清理、Provider 异常退出清理及模型工具注册。
