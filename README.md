# AITools

AITools 是一个本地运行的 Agent 工作台。后端使用 FastAPI 管理节点、图运行、Provider、文件和运行状态，前端使用 Vue 3 + Vite 提供可视化节点编辑、运行控制、Memory 查看和文件操作。

## 主要能力

- 可视化 Graph/Node 工作流：创建节点、连线、保存图、启动 Graph Runner。
- Agent 节点运行：支持流式输出、工具调用、工具调用历史、节点 memory 持久化和停止控制。
- 多 Provider 接入：当前代码支持 Doubao、Gemini、OpenAI 兼容接口、Zhipu、Hyper3D 等 Provider 类型。
- 多模态和生成类节点：包含图片生成、视频生成、换人视频、3D 模型生成、模型贴图生成等节点。
- 本地工具系统：`functions/` 下的 Python 工具会被 Agent 节点加载使用。
- 文件和资源管理：WebUI 可以浏览、读取、写入、上传文件，并通过 `/memories` 暴露运行资源。
- 移动端/远端入口：包含 mobile API 和 remote 配置，用于从其他设备访问本机工作流。
- 通道节点：包含微信 receiver/sender 等 channel 相关节点。

## 目录结构

```text
AITools/
  config/              # 服务配置、Provider 配置、Prompt 文本
  functions/           # Agent 可调用工具
  memories/            # Graph/Node 运行记忆；节点当前记忆在根目录，超量后归档到 archive/YYYY-MM-DD/
  nodes/               # 可视化工作流节点实现
  scripts/             # 重启等辅助脚本
  skills/              # Agent skill 文档
  src/                 # FastAPI 后端、Provider、协议、运行时
  tests/               # pytest 测试
  webui/               # Vue 3 + Vite 前端
```

## 环境要求

- Windows 是当前主要使用环境，部分功能依赖 `.bat`、PowerShell、桌面自动化或 PyInstaller 打包路径。
- Python 3.11+。项目脚本会优先寻找本机 Python 3.14/3.12/3.11，也可以直接使用 `python`。
- Node.js + npm，用于安装和构建 `webui`。
- ripgrep `rg` 推荐安装，文件搜索工具和部分前端搜索能力会优先使用它。

## 安装

在项目根目录安装后端依赖：

```bat
python -m pip install -e .
```

安装前端依赖：

```bat
cd webui
npm install
```

## 配置

主配置文件在 `config/config.json`：

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

- `server.host` 和 `server.port` 控制 FastAPI 监听地址。端口被占用时，启动入口会自动向后寻找可用端口。
- `nodeMemory.maxEntries` 控制每个节点当前 `memory.md` / `messages.jsonl` 保留的最大条目数，默认 20；超过后旧记录归档到 `archive/YYYY-MM-DD/`。
- WebUI 默认打开的 Graph 属于本机运行状态，存储在 `.cache/startup_graph.json`，该目录不提交到 Git。

Provider 配置在 `config/moduleProvider.json`。每个 Provider 通常包含：

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

常见 `type` 包括 `doubao`、`gemini`、`openai`、`zhipu`、`hyper3d`。不要把真实 API Key 提交到公共仓库。

## 启动方式

### 一键构建并启动

Windows 下推荐直接运行：

```bat
build_and_run.bat
```

这个脚本会：

- 检查 Python 和 `rg`。
- 安装缺失的前端依赖。
- 执行 `webui` 构建。
- 执行 `python -m pip install -e .`。
- 启动 `python -m src.fast_api --workspace-root <项目根目录>`。

启动后浏览器会自动打开服务地址。默认端口来自 `config/config.json`，当前配置为 `8788`。

### 生产模式

先构建前端静态资源：

```bat
cd webui
npm install
npm run build
```

回到项目根目录启动后端：

```bat
cd ..
python -m src.fast_api --host 127.0.0.1 --port 8788
```

打开：

```text
http://127.0.0.1:8788/
```

如果不希望启动时自动打开浏览器，可以加 `--no-browser`：

```bat
python -m src.fast_api --host 127.0.0.1 --port 8788 --no-browser
```

### 开发模式

先启动后端：

```bat
python -m src.fast_api --host 127.0.0.1 --port 8788 --no-browser
```

再启动 Vite：

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

Windows 下可以运行：

```bat
Restart.bat
```

脚本会尝试停止当前 AITools 服务、执行 `git pull --rebase`，然后通过 `build_and_run.bat` 重新启动。

WebUI 内部也可以调用 `/api/system/restart` 触发重启流程。

## 打包

Windows 下使用：

```bat
package.bat
```

脚本会构建前端，并用 PyInstaller 打包后端入口 `src/fast_api.py`，产物为：

```text
dist/AITools.exe
```

打包完成后会把 `config/`、`functions/`、`nodes/` 复制到 `dist/`，这些目录会作为运行时资源使用。

## 常用接口

- `GET /api/providers`：列出 Provider。
- `GET /api/tools`：列出 `functions/` 工具。
- `GET /api/nodes`：列出可用节点。
- `GET /api/graphs`：列出 Graph。
- `POST /api/graphs/{graph_id}/runner/start`：启动 Graph Runner。
- `POST /api/graphs/{graph_id}/emit`：向 Graph 中某个节点发送输入。
- `GET /api/nodes/instances/{node_id}/memory`：读取节点 memory。
- `POST /api/nodes/instances/{node_id}/control`：控制节点运行状态。
- `POST /api/files/upload`：上传文件。
- `POST /api/system/restart`：触发服务重启。

完整路由注册在 `src/web_backend/route_registry.py`。

## 测试

项目测试使用 pytest：

```bat
python -m pytest
```

也可以只运行某个测试文件：

```bat
python -m pytest tests/test_node_stop_cancellation.py
```

## 开发约定

- 新增节点放在 `nodes/`，节点元数据、schema、输入输出能力应保持清晰。
- 新增 Agent 工具放在 `functions/`，工具返回值应保持结构化，避免吞掉真实错误。
- Provider 相关逻辑放在 `src/providers/`，优先复用已有 transport、runtime event、tool call 协议。
- 后端 API 路由集中注册在 `src/web_backend/route_registry.py`。
- WebUI API 调用集中在 `webui/src/api.ts` 和 `webui/src/uploadApi.ts`。
- 单文件超过 400 行时优先评估按职责拆分。

## CLI and Recovery

AITools also has an offline CLI for cases where FastAPI or WebUI is unavailable:

```bat
python -m src.cli chat
python -m src.cli chat --message "hello"
python -m src.cli chat --debug-terminal
python -m src.cli doctor
python -m src.cli capabilities list --graph <graph_id> --node <node_id>
python -m src.cli capabilities enable --kind skill --name <skill_id> --graph <graph_id> --node <node_id>
python -m src.cli config validate --graph <graph_id> --node <node_id>
```

`chat` starts the dedicated companion Agent. Its config and conversation state live under `memories/companion/`, using the same Agent-node config fields as normal nodes:

```text
memories/companion/config.json
memories/companion/memory.md
memories/companion/messages.jsonl
```

After the normal build/install flow, `build_and_run.bat` starts the WebUI server in the background, opens the browser from that server process, and then starts the interactive companion CLI in the current terminal. `build_and_run.bat cli` and `build_and_run.bat chat` use the same combined Web + CLI startup. Use `build_and_run.bat server` or `build_and_run.bat web` when only the WebUI server should run, and `build_and_run.bat cli-only` when the CLI should run without starting WebUI.
The companion CLI runs the same Agent turn path as normal nodes and stores state in `memories/companion/`. If the terminal does not accept input, run `build_and_run.bat cli --debug-terminal`; interactive input diagnostics fail loudly instead of silently downgrading.
Inside the companion CLI, `/restart` launches the repository `Restart.bat` and exits the current CLI session so restart behavior stays on the canonical startup path.

Node config reads and writes are documented in `docs/config-contract.md`. Runtime state recovery is documented in `docs/runtime-state-machine.md`. Provider feature support is documented in `docs/provider-feature-matrix.md`. Capability descriptors and dependency reporting are documented in `docs/capability-system.md`. Skill/plugin authoring is documented in `docs/skill-plugin-authoring.md`. Long-term sidecar, caching, and distribution boundaries are documented in `docs/long-term-architecture.md`. Recovery steps are documented in `docs/troubleshooting.md`.

Packaged builds expose the same offline recovery commands through the executable:

```bat
dist\AITools.exe doctor --json
dist\AITools.exe capabilities list --graph <graph_id> --node <node_id> --json
```

`package.bat` copies `docs/`, `skills/`, and `plugins/` into `dist/` so packaged doctor checks and default capability discovery use the same bundled resources as source checkout runs.

