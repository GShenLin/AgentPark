# AgentPark

[English](./README.md) | [中文](./README.zh.md)

AgentPark 是一个用于构建、运行和分享 Agent、工具与 Graph 工作流的 Agent 平台。它从本地优先的工作区出发，但产品方向不止于本地执行：让 Agent 可以复用，让工具能力显式化，让 Graph 成为可以沉淀和分享的自动化资产，而不是一次性的本地实验。

后端使用 FastAPI 管理节点、图执行、模型服务商、文件、设置和运行时状态。前端使用 Vue 3 + Vite，提供可视化图编辑、节点执行控制、记忆浏览、文件操作、桌面端设置，以及适合手机访问的移动端工作区。

## 项目目标

AgentPark 的目标是成为一个实用的 Agent 创建与分享平台：

- Agent 应该是可配置的运行单元，包含记忆、服务商设置、工具、技能、插件和清晰的执行历史。
- 工具应该是结构化能力，可以被发现、测试、复用，并在 Agent 和 Graph 之间共享。
- Graph 应该描述完整工作流，包括触发、路由、生成节点、外部通道和可恢复的运行时状态。
- 本地开发仍然是一等能力，同时项目会逐步走向更清晰的打包方式、可迁移资产和可分享的 Agent/Tool/Graph 资源库。
- 平台边界应该保持显式：节点契约、服务商能力、运行时状态、工具调用协议和 UI/API 契约都应该清楚可见，而不是被脆弱的兜底逻辑隐藏。

## 项目前景

长期方向是形成 AgentPark 式生态：用户可以可视化设计 Agent，把它们连接成 Graph，挂载可复用工具和技能，然后发布或交换这些资产。当前项目已经具备本地运行时、可视化编辑器、服务商集成、移动端访问、CLI 恢复路径，以及节点、工具、插件等基础。后续工作应继续把这些基础沉淀为稳定的分享格式、更强的能力元数据、更可靠的运行时恢复和更简单的分发方式。

## 主要功能

- 可视化 Graph/Node 工作流：创建节点、连接端口、保存完整 Graph 工作流，并启动 Graph Runner。
- Agent 执行：流式输出、工具调用、工具调用历史、持久化节点记忆，以及停止/取消控制。
- 服务商集成：豆包、Gemini、OpenAI 兼容接口、智谱、Hyper3D，以及服务商能力元数据。
- 多模态生成节点：图片生成、视频生成、换人视频生成、3D 模型生成、3D 贴图生成。
- 本地工具系统：`functions/` 下的 Python 工具会加载为 Agent 节点可调用的结构化、可复用能力。
- 面向分享的资产模型：Agent、工具、技能、插件和 Graph 都被视为项目资产，可逐步演进为可迁移、可交换的格式。
- 文件和资源管理：WebUI 可以浏览、读取、写入、上传文件，并通过 `/memories` 暴露生成资源。
- 桌面端设置入口：右上角 `Settings` 按钮可以直接打开设置界面，包括 providers、defaults、companion settings 和 provider limit tests。
- 手机端支持：宽度不超过 760px 时自动使用移动端工作区，支持适合手机的 PC/graph/node 导航、聊天、流式回复、附件、节点配置、重启、图编辑和设置入口。
- 远程访问：远程端点管理和移动端 API 支持在同一网络的其他设备上操作工作流。
- Channel 节点：用于 OpenClaw Weixin 等外部通道的 receiver/sender 节点。

## 节点功能列表

节点实现位于 `nodes/`。后端通过 `GET /api/nodes` 暴露节点元数据，并通过 `GET /api/nodes/{type_id}/template` 暴露节点模板，内容包括 schema、端口数量、输入/输出能力和运行时声明。节点的 `type_id` 通常是去掉 `.py` 后缀的节点文件名；例如 `nodes/agent_node.py` 会暴露为 `agent_node`。

所有节点都继承这些通用配置字段：

- `skills`：为当前节点加载 `skills/` 下的 Skill 文档和脚本。
- `plugins`：为当前节点加载项目插件能力。
- `working_path`：选中节点时文件浏览器打开的目录；Agent 和命令节点也会把它作为工作目录上下文。

### Agent 和自动化节点

| 节点        | `type_id`        | 功能                                                                                                                                                                                                                                                                 |
| --------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Agent     | `agent_node`     | 通用 LLM Agent 节点。接收文本、图片、视频、音频、文档、文件、URL、结构化数据和 meta 输入。输出文本、生成的图片/视频资源、结构化数据、工具调用和 meta。支持 `provider_id`、`mode`、`system_prompt`、本地 `tools`、`mcp_servers`、`skills` 和 `plugins`。服务商能力可启用 `web_search`、`thinking` 和 `reasoning_effort`。运行时支持持久化节点记忆、流式消息、工具调用历史和停止控制。 |
| GUI Agent | `gui_agent_node` | 单节点 GUI 自动化循环。捕获屏幕截图，调用视觉/多模态服务商规划操作，执行鼠标、键盘、滚动动作，并可验证任务是否完成。支持 `instruction`、planner/verify prompt、截图区域、dry run、mock actions、planner timeout 和 verify timeout。适合本地桌面或远程 GUI 操作。                                                                                   |

### 生成类节点

| 节点                          | `type_id`                       | 功能                                                                                                                                                                     |
| --------------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Image Generation            | `image_generation_node`         | 根据 prompt 和可选参考图生成图片。支持 `aspect_ratio`、`image_size`、`response_format`、`watermark` 和 `filename_prefix`。输出图片资源和结构化生成元数据。所选服务商必须在 `supportmode` 中声明支持 `image_generation`。 |
| Video Generation            | `video_generation_node`         | 根据文本、首帧/尾帧图片、参考图、参考视频和参考音频生成视频。支持分辨率、宽高比、时长、seed、生成音频、水印、返回尾帧、回调、任务过期、安全标识、web search、public base URL 和输出文件名前缀。输出视频资源、可选尾帧图片资源和结构化任务元数据。                               |
| Video Change Person         | `video_change_person_node`      | 使用 Wan Animate Mix 风格服务商，把参考视频中的主体替换为肖像图片。需要一张肖像图片和一个参考视频。支持 `wan-std`/`wan-pro`、水印、图片检查、public base URL 和输出文件名前缀。输出换人后的视频资源和任务元数据。                                    |
| 3D Model Generation         | `model_generation_node`         | 使用 Hyper3D/Rodin 风格服务商进行文生 3D 或图生 3D。支持多张参考图、Gen-2/Regular 档位、alpha 处理、seed、导出格式、材质类型、质量、面数覆盖、T/A pose、包围盒尺寸、Raw/Quad mesh、HighPack、预览渲染和高清纹理。输出下载后的模型文件资源和任务元数据。      |
| 3D Model Texture Generation | `model_texture_generation_node` | 为已有 3D 模型生成或重绘贴图。接收模型文件或 URL、参考图和可选 prompt。支持 seed、reference scale、导出格式、材质和分辨率。输出重绘贴图后的模型文件资源和任务元数据。                                                                   |

### 触发、控制和路由节点

| 节点              | `type_id`            | 功能                                                                                 |
| --------------- | -------------------- | ---------------------------------------------------------------------------------- |
| BasicTrigger    | `basic_trigger_node` | 手动触发节点。触发时输出配置的 `OutputText`。常用于工作流起点或调试入口。                                        |
| TimerTrigger    | `timer_trigger_node` | 定时触发节点。在达到配置的 `ScheduleAt` 时间后输出 `OutputText`。                                     |
| Clock           | `clock_node`         | 周期触发节点。按天/小时/分钟/秒间隔输出 `OutputText`。支持重复执行和 `LoopCount`，并保存当前运行状态、下次触发时间、剩余时间和触发次数。 |
| Loop            | `loop_node`          | 循环控制节点。收到输入后，循环仍在进行时使用输出端口 0，循环结束时使用输出端口 1。支持固定次数循环和无限循环，剩余次数会持久化到节点配置中。           |
| Event           | `event_node`         | 事件分发节点。转发输入消息并附加 `EventKey`，便于下游路由或图运行时按事件 key 分发。                                 |
| MultiInput      | `multi_input_node`   | 多输入聚合节点。根据 `InputCount` 动态创建输入端口，缓存每个端口的消息，等所有端口都有输入后，按端口顺序合并文本并输出。                |
| InputOutputTest | `input_output_test`  | 拓扑测试节点，包含 3 个固定输入和 4 个固定输出。适合验证连接、端口索引和路由行为。                                       |

### 文本、文件和命令节点

| 节点             | `type_id`              | 功能                                                                                                                              |
| -------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Echo           | `echo_node`            | 回显输入消息。可选 `MyText` 会作为前缀，因此输出为 `MyText + input text`。                                                                           |
| Append         | `append_node`          | 将 `AppendText` 追加到输入文本后。适合简单 prompt 拼接或后缀格式化。                                                                                   |
| Response       | `response_node`        | 返回固定响应。如果配置了 `MyText`，则输出该值；否则返回输入文本。适合作为终点、占位或测试节点。                                                                            |
| SaveFile       | `save_file_node`       | 将输入文本保存到文件。使用 `FilePath` 和可选 `FileName`；未提供文件名时，会从内容开头推导文件名；无扩展名时默认使用 `.md`。保存后输出原文本。                                           |
| ConsoleCommand | `console_command_node` | 执行 shell 命令。如果 `Command` 为空，则使用输入文本作为命令。支持 `TimeoutSeconds`、`Shell` 和节点 `working_path`。有 3 个输出端口：stdout、stderr 和返回码。取消节点会终止子进程。 |

### 外部通道节点

| 节点              | `type_id`               | 功能                                                                                                              |
| --------------- | ----------------------- | --------------------------------------------------------------------------------------------------------------- |
| ChannelReceiver | `channel_receiver_node` | 从外部通道接收消息并向下游转发。内置通道为 OpenClaw Weixin。支持通过 `Name` 进行命令激活、持久化 `Active` 状态、`AutoStart` 和轮询超时。可转发文本、结构化数据、文件和图片资源。 |
| ChannelSender   | `channel_sender_node`   | 将上游输出发送回外部通道。目前支持 OpenClaw Weixin。可配置账号、接收者、发送者名称和超时。如果没有显式目标，会尝试使用最近一条入站消息中的默认目标。支持文本和图片资源，并输出结构化发送结果。         |

## 桌面端和手机端 UI

- 桌面端用于较宽屏幕，包含完整可视化图编辑器、顶部栏、远程切换器、文件/记忆面板、节点控制，以及右上角直接进入 `Settings` 的入口。
- 手机端在视口宽度不超过 760px 时自动启用。它提供适合手机的流程：选择 PC、选择图、列出节点、与节点聊天、上传附件、查看实时流式输出、保存/复制/删除消息、清空 memory、打开节点配置、创建/删除节点、保存/删除图、重启工作区，以及从 header 打开 Settings。
- 远程端点可从桌面端顶部栏添加，并存储在 `config/remote.json`；移动端 API 使用这些端点浏览 PC、图、节点、会话和消息。

## 项目结构

```text
AgentPark/
  config/              # 服务配置、服务商配置、prompt 文本、远程端点
  functions/           # Agent 节点可调用的工具
  memories/            # 图/节点记忆；当前记忆在根目录，溢出内容按日期归档
  nodes/               # 可视化工作流节点实现
  scripts/             # 辅助脚本
  skills/              # Agent skill 文档
  src/                 # FastAPI 后端、服务商、协议、运行时
  tests/               # pytest 测试
  webui/               # Vue 3 + Vite 前端
```

## 环境要求

- Windows 是主要目标环境。部分功能依赖 `.bat`、PowerShell、桌面自动化或 PyInstaller 打包路径。
- Linux 支持 WebUI、CLI、provider runtime 和重启流程；Windows 桌面与打包功能仍仅支持 Windows。
- Python 3.11+。Windows 脚本优先使用本地 Python 3.14/3.12/3.11；Linux 脚本依次尝试 `AgentPark_Linux_env`、`.venv`、`python3` 和 `python`。
- Node.js + npm，用于安装和构建 `webui`。
- 推荐安装 ripgrep `rg`；文件搜索工具和部分前端搜索路径会优先使用它。

## 安装

在仓库根目录安装后端依赖：

```bat
python -m pip install -e .
```

安装前端依赖：

```bat
cd webui
npm install
```

## 配置

主服务配置位于 `config/config.json`：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8788
  },
  "agentNode": {
    "minSendDelayMs": 200,
    "historyMessageLimit": 40
  },
  "nodeMemory": {
    "maxEntries": 20
  }
}
```

- `server.host` 和 `server.port` 控制 FastAPI 监听地址。如果端口被占用，启动流程会寻找下一个可用端口。
- `nodeMemory.maxEntries` 控制每个节点在当前 `memory.md` / `messages.jsonl` 中保留多少条记录。更早的记录会归档到 `archive/YYYY-MM-DD/`。
- 启动图存储在 `.cache/startup_graph.json`；该目录不会提交到 Git。

服务商配置位于 `config/moduleProvider.json`。典型配置如下：

```json
{
  "providers": {
    "example": {
      "type": "openai",
      "apiKey": "YOUR_API_KEY",
      "baseUrl": "https://example.com/v1",
      "model": "model-name",
      "supportmode": ["chat", "imagechat"],
      "timeoutMs": 60000
    }
  }
}
```

常见 `type` 包括 `doubao`、`gemini`、`openai`、`zhipu` 和 `hyper3d`。不要把真实 API key 提交到公开仓库。

## 启动

### 构建并运行

Windows 下推荐入口：

```bat
build_and_run.bat
```

Linux 下使用：

```sh
./build_and_run.sh
```

两个平台脚本都会：

- 检查 Python 和 `rg`。
- 安装缺失的前端依赖。
- 构建 `webui`。
- 运行 `python -m pip install -e .`。
- 启动 `python -m src.fast_api --workspace-root <repo root>`。

启动后会自动打开浏览器。默认端口来自 `config/config.json`，当前默认值为 `8788`。

### 生产模式

先构建前端静态文件：

```bat
cd webui
npm install
npm run build
```

然后回到仓库根目录并启动后端：

```bat
cd ..
python -m src.fast_api --host 127.0.0.1 --port 8788
```

打开：

```text
http://127.0.0.1:8788/
```

如需禁止自动打开浏览器，添加 `--no-browser`：

```bat
python -m src.fast_api --host 127.0.0.1 --port 8788 --no-browser
```

### 开发模式

启动后端：

```bat
python -m src.fast_api --host 127.0.0.1 --port 8788 --no-browser
```

启动 Vite：

```bat
cd webui
npm run dev
```

打开 Vite 地址：

```text
http://localhost:5173/
```

`webui/vite.config.ts` 会把前端 API 请求代理到后端。

### 重启

Windows 下运行：

```bat
Restart.bat
```

Linux 下运行：

```sh
./Restart.sh
```

对应平台的重启脚本会尝试停止当前 AgentPark 服务，在工作区干净时更新代码，并通过对应的构建启动脚本重启。

WebUI 也可以调用 `/api/system/restart` 触发重启流程。

## 打包

Windows 下运行：

```bat
package.bat
```

脚本会构建前端，并使用 PyInstaller 打包后端入口 `src/fast_api.py`。输出文件：

```text
dist/AgentPark.exe
```

打包后，`config/`、`functions/` 和 `nodes/` 会复制到 `dist/` 作为运行时资源。

## 常用 API 端点

- `GET /api/providers`：列出服务商。
- `GET /api/tools`：列出 `functions/` 下的工具。
- `GET /api/nodes`：列出可用节点类型。
- `GET /api/graphs`：列出图。
- `POST /api/graphs/{graph_id}/runner/start`：启动 Graph Runner。
- `POST /api/graphs/{graph_id}/emit`：向图节点发送输入。
- `GET /api/nodes/instances/{node_id}/memory`：读取节点记忆。
- `POST /api/nodes/instances/{node_id}/control`：控制节点运行时状态。
- `POST /api/files/upload`：上传文件。
- `POST /api/system/restart`：触发服务重启。
- `GET /api/settings`：列出设置分区。
- `GET /api/settings/{section}`：读取设置文档。
- `POST /api/settings/{section}`：更新设置文档。
- `GET /api/remotes`：列出远程端点。
- `POST /api/remotes`：添加远程端点。
- `DELETE /api/remotes/{remote_id}`：删除远程端点。
- `GET /api/mobile/pcs`：列出移动端 PC 条目。
- `GET /api/mobile/pcs/{pc_id}/graphs`：列出移动端可访问的图。
- `GET /api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes`：列出移动端可访问的图节点。
- `GET /api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes/{node_id}/conversation`：在移动端读取节点会话。
- `POST /api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes/{node_id}/messages`：在移动端向节点发送消息。

完整路由注册位于 `src/web_backend/route_registry.py`。

## 测试

使用 pytest 运行全部测试：

```bat
python -m pytest
```

运行单个测试文件：

```bat
python -m pytest tests/test_node_stop_cancellation.py
```

## 开发约定

- 新节点添加到 `nodes/`；保持 metadata、schema、输入/输出能力和端口声明清晰。
- 新 Agent 工具添加到 `functions/`；工具返回值应保持结构化，不要隐藏真实错误。
- 服务商逻辑放在 `src/providers/`；优先使用现有 transport、runtime event 和 tool-call 协议。
- 后端 API 路由注册在 `src/web_backend/route_registry.py`。
- WebUI API 调用集中在 `webui/src/api.ts`、`webui/src/uploadApi.ts` 和 `webui/src/settingsApi.ts`。
- 单个文件超过约 400 行时，优先按职责拆分。

## CLI 和恢复

AgentPark 也提供离线 CLI，用于 FastAPI 或 WebUI 不可用的情况：

```bat
python -m src.cli chat
python -m src.cli chat --message "hello"
python -m src.cli chat --debug-terminal
python -m src.cli doctor
python -m src.cli capabilities list --graph <graph_id> --node <node_id>
python -m src.cli capabilities enable --kind skill --name <skill_id> --graph <graph_id> --node <node_id>
python -m src.cli config validate --graph <graph_id> --node <node_id>
```

`chat` 会启动专用 Companion Agent。Companion 是一个受保护的普通 graph，里面有一个普通 Agent 节点，使用与其他节点相同的配置字段：

```text
memories/Companion/config.json
memories/Companion/Companion/config.json
memories/Companion/Companion/memory.md
memories/Companion/Companion/messages.jsonl
```

正常构建/安装流程完成后，Windows 使用 `build_and_run.bat`，Linux 使用 `build_and_run.sh`；脚本会在后台启动 WebUI 服务，然后在当前终端启动交互式 companion CLI。`cli` 和 `chat` 使用 Web + CLI 组合模式；`server` 或 `web` 只运行 WebUI；`cli-only` 只运行 CLI。

companion CLI 使用与普通节点相同的 Agent turn 流程，并把状态存储在 `memories/Companion/Companion/`。如果终端不接受输入，使用对应平台的构建启动脚本运行 `cli --debug-terminal`；交互式输入诊断会明确失败，而不是静默降级。

在 companion CLI 中，`/restart` 会在 Windows 启动 `Restart.bat`，在 Linux 启动 `Restart.sh`，然后退出当前 CLI 会话，确保重启行为仍走标准启动路径。

节点配置读写见 `docs/config-contract.md`。运行时状态恢复见 `docs/runtime-state-machine.md`。服务商功能支持见 `docs/provider-feature-matrix.md`。能力描述符和依赖报告见 `docs/capability-system.md`。Skill/plugin 作者指南见 `docs/skill-plugin-authoring.md`。长期 sidecar、缓存和分发边界见 `docs/long-term-architecture.md`。恢复步骤见 `docs/troubleshooting.md`。

打包版本通过可执行文件暴露相同的离线恢复命令：

```bat
dist\AgentPark.exe doctor --json
dist\AgentPark.exe capabilities list --graph <graph_id> --node <node_id> --json
```

`package.bat` 会把 `docs/`、`skills/` 和 `plugins/` 复制到 `dist/`，因此打包后的 doctor 检查和默认能力发现会使用与源码 checkout 相同的资源。
