# 本地模型（LocalModel）

设置 → 本地模型用于手动管理 AgentPark 后端所在电脑的 Strata、ComfyUI 实例。
服务登记保存在 `config/localModel.json`。不自动加载、卸载、调度，不向 Agent 默认提供管理工具。

## 配置与操作

- 安装目录：Strata 的 `serve/server.py` 所在根目录；ComfyUI 的 `main.py` 所在目录。
- Python：可显式配置；留空使用安装目录的 `.venv`。便携 ComfyUI 应指定外部 `python_embeded/python.exe`。
- 服务地址：带端口的本机 HTTP 根地址，不带 `/v1`。
- 附加启动参数：每行一个参数；例如 ComfyUI 的 `--lowvram`。服务地址由独立字段管理。
- 启动服务：Strata 使用 `--lazy`，启动 HTTP 服务时不加载权重；ComfyUI 等待工作流才加载模型。
- 停止服务：仅停止当前 AgentPark 进程启动且仍持有进程句柄的服务。外部启动或 AgentPark 重启前启动的服务需在原入口停止。
- 检测不执行推理。文件存在只说明静态检查通过，不等于格式兼容或推理成功。

## 模型边界

Strata 扫描安装目录的 `strata*.json`，检查引擎及 pack/native/PLE 路径。
添加模型是登记已有运行配置，保留原权重位置，不执行下载或格式转换。
通过 `/health` 识别服务，`/v1/load`、`/v1/unload` 手动操作模型并检查返回状态。
切换不同配置需要停止当前实例后重新启动，不修改既有 Provider 配置。

ComfyUI 扫描模型目录、`extra_model_paths.yaml`；在线时同时读取服务模型清单。
添加本地模型会复制文件到指定类别，不覆盖同名文件。
工作流必须为 API 格式 JSON；“执行工作流”提交真实生成任务，不是通用的单文件预加载。
释放模型调用 `/free`，先检查任务队列为空。该接口异步处理且没有逐模型完成回执，界面只报告请求已提交。

## 实现与验证

- `src/local_model/`：合同、登记、引擎适配、HTTP 和手动操作作业。
- `src/web_backend/local_model_api.py`：所有者权限路由 `/api/local-model`。
- HTTP 使用项目的 `CurlHttpTransport`；子进程使用参数数组，不使用 shell。
- 同一实例同时只执行一个操作。操作期间不能修改或移除该实例；检测结果不触发动作。
- 作业历史在内存中，AgentPark 重启后不保留；配置持久化。
- 测试：`python -m pytest tests/test_local_model.py tests/test_http_transport_boundary.py -q`；前端 `npm run build`。
