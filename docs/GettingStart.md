# GettingStart：从启动到第一次任务

[返回项目介绍](../README.md) · [Docs 索引](README.md) · [Settings 手册](settings/README.md)

目标是先运行一个能正常回答的 Agent，再逐步接入工具、知识库和协作。模型账号、外部 CLI 和本地模型权重不会随仓库自动获得。

## 1. 理解三个配置层级

| 名称 | 管理什么 | 举例 |
| --- | --- | --- |
| Provider | API 类型、地址、授权、可选模型、并发与协议 | 一个 OpenAI 兼容服务连接 |
| Preset / Agent Profile | 节点类型、所选 Provider/Model、指令、工具与事件 | 一个“代码审查”角色 |
| Node | Graph 中的实际实例、工作路径、运行状态和历史 | 当前项目的审查 Agent |

先配置 Provider，再在实际节点选择 Provider 和 Model。Preset 用来复用配置；Companion、历史压缩和长期记忆还会引用推理预设。

## 2. 准备运行环境

| 项目 | 准备方式与用途 |
| --- | --- |
| 项目源码 | 放到可写目录；命令均从项目根目录执行 |
| Python + pip | 建议从 Python 3.12 开始；依赖列表以根目录 `pyproject.toml` 为准 |
| Node.js + npm | WebUI / Windows 小窗使用 Node.js 22.12+；额外 Harness 还需满足自身要求 |
| Git | 用于获取与更新代码；Windows 启动器会在工作区干净且存在上游时尝试更新 |
| 网络 | 首次安装需下载 Python/npm 包，模型调用需要可达的服务地址 |
| 模型授权 | 自备 API Key 或受支持的官方 OAuth 账号 |

Windows 提供桌面操作及 Electron 节点小窗；Linux/macOS 可运行后端和网页，不能直接使用 Windows 原生桌面工具。Termux 需要另外处理原生依赖和所选 Harness 的 Python 版本，不按桌面环境的安装成功来推断其可用性。

## 3. 选择启动方式

### Windows 一键入口

PowerShell：

```powershell
Set-Location 'D:\Project\AgentPark'
.\build_and_run.bat
```

将路径替换为实际检出目录。该入口不接受参数，主要执行：

1. 检查仓库更新；有本地改动时跳过更新。
2. 检查并准备项目私有 CA 信任；缺少 Python/Node 时尝试通过 winget 安装。
3. 准备 Windows 节点小窗运行时和相关本机集成。
4. 安装 WebUI 依赖并构建，尝试一次云端前端发布；发布失败会记录日志并继续本地启动。
5. 安装 Python 项目依赖，停止同一工作区的旧进程，启动后台 Web 服务并核验就绪。
6. 启动 Companion CLI；其所选预设需要可用的模型授权。

因此，第一次只想分步配置本机服务、尚未配置 Companion 或不准备执行上述集成步骤时，可先使用下文的手动启动。不要同时运行两种入口来管理同一实例。

### Linux / macOS 脚本入口

POSIX shell：

```sh
cd /path/to/AgentPark
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
PYTHON_BIN="$(pwd)/.venv/bin/python" sh ./build_and_run.sh server
```

`server`（也可写 `web`）安装依赖、构建并以前台方式运行 Web 服务，不启动 Companion。已准备好的 Python 环境可通过 `PYTHON_BIN` 指定。需要终端伴侣时，在交互式终端使用 `sh ./build_and_run.sh cli`；`cli-only` 仅运行 CLI。默认无参数且终端不具备交互条件时会选服务器模式。

### 手动分步启动

适合首次配置、虚拟环境开发和查看原始报错。以下操作只启动本机 Web 服务；Windows 桌面小窗依赖可之后单独安装。

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
npm --prefix webui install
npm --prefix webui run build
.\.venv\Scripts\python.exe -m src.fast_api
```

Linux / macOS：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
npm --prefix webui install
npm --prefix webui run build
.venv/bin/python -m src.fast_api
```

手动运行使用当前命令指定的 Python；Windows 一键入口会按其工具链检测顺序选择 Python，不保证采用已激活的 `.venv`。排错时应确认安装依赖和运行后端使用的是同一个解释器。

后端默认读取 `config/config.json`，默认监听 `0.0.0.0:8766`。打开 [http://127.0.0.1:8766](http://127.0.0.1:8766)；若配置了其他端口或端口已占用，查看控制台实际监听地址。`0.0.0.0` 是监听地址，浏览器使用 `127.0.0.1`、`localhost` 或设备的实际 IP。

需要临时指定监听地址时：

```powershell
python -m src.fast_api --host 127.0.0.1 --port 8766
```

该命令中的 `python` 也应替换为安装依赖的解释器。服务启动完成后再进行下面的网页配置。

## 4. 配置第一个 Provider

1. 从本机网页右上角打开 **Settings / 设置 → 模型提供商**。
2. 选择已有 Provider 或输入唯一 ID 后点击添加。ID 用于节点引用，例如 `my-chat`。
3. 选择与你实际接口匹配的 Type，填写服务的 Base URL。不要把完整的 `/responses` 或 `/chat/completions` 随意追加到根地址。
4. 使用 **API Key Name → Add** 创建一个密钥引用，输入名称和真实密钥并保存，再选中该名称。已有密钥可直接选择；真实密钥写入本机 `.auth/`。
5. 或在支持的类型上开启 **OAuth**，按登录流程完成授权，选中对应账号。也可使用面板中的命名 API Key 账号方式。
6. 在 Models 中填写服务实际支持的模型 ID，至少保留一个；对话连接应声明 `chat` 能力。按服务实际支持情况选择 Responses 及其他参数。
7. 点击页顶 **保存**，解决配置警告。密钥引用的保存和 Provider 草稿的保存是两个动作。

第一次不要复制其他机器的 `.auth/`。仓库中的 Provider 名称和节点预设是配置资源，并不代表你的设备已经获得对应账号。

详细字段、协议选择及账号绑定见 [模型手册](settings/models.md)。如果模型列表未知，可到 **提供商测试 → Models** 查询；查询失败需检查服务是否提供模型目录接口。

## 5. 创建节点并验证

1. 返回 Board，在画板空白处右键，搜索并选择 **Agent**。
2. 填写名称，选择刚保存的 Provider 和一个明确的 Model。工作目录填写后端机器上实际存在的目录。
3. 初次测试先不增加外部工具和复杂事件；创建节点。
4. 打开节点聊天，发送“请用一句话说明你能做什么”。
5. 等待最终回答，查看节点状态和过程；若失败，保留原始错误再按下面的排查表定位。
6. 接着尝试上传一张图片或一个文件，验证所选模型确实具备所需输入能力。

创建菜单和节点字段由后端 schema 生成，不同 Provider、访问权限和节点类型显示的选项可能不同。模型不存在时应更正模型 ID，不能仅修改显示名称。

## 6. 配置可复用角色与 Companion

1. 调试好普通 Agent 的模型、指令和能力后，通过节点的保存预设操作保存角色。
2. 打开 **Settings → 节点预设**，选中该角色，核对 Node configuration 和元数据，点击 **Save Profile**。
3. 打开 **伴侣 / Companion**，选择可用的 `agent_node` 预设和 Working Path，保存。
4. 打开 **默认设置**，为“当前对话上下文”和“节点长期记忆”的模型任务选择可用的推理预设。内置默认预设的 Provider 也必须完成授权。
5. 需要粘贴创建 Agent 时，在 **Paste Agent** 的独立保存区选择预设并保存。

普通 Agent 的基本问答不等于后台摘要模型已经配置成功。对话压缩和长期记忆会另外发起模型请求，应一起检查其引用预设。见 [默认设置](settings/defaults.md)和[预设与 Companion](settings/presets-companion.md)。

## 7. 从简单任务逐步升级

| 想做的事 | 下一步 |
| --- | --- |
| 让 Agent 查询本地笔记或表格 | [添加知识库](settings/knowledge.md)，完成扫描，再在节点选择 `knowledge` Skill |
| 使用专门的任务流程 | [Skill 管理](settings/skills.md)，阅读依赖并在节点选择 |
| 使用 Codex 等编程 Agent | [Harness](settings/models.md#harness)，检查安装，再创建对应节点 |
| 让多个 Agent 分工 | [协作组](agent-groups-guide.md)，框选后按 G，明确角色、任务和验收证据 |
| 管理 ComfyUI / Strata | [本地服务](settings/local-services.md)，先检测，再手动启动或执行工作流 |
| 从手机或另一台电脑使用 | [设备互联](settings/connectivity.md)，区分远程 Board、远程执行和同步 |
| 追踪一次失败或耗时 | [统计与诊断](settings/diagnostics.md)，查看完整工具结果与请求用量 |

## 8. 保存、重启与数据位置

模型、默认设置、Companion 和主题使用页顶保存；运行事件使用“应用”。Harness、知识库、Skills、网关等专用面板使用各自按钮。出现“未保存”时，不要把重新加载当成保存。

| 位置 | 内容 |
| --- | --- |
| `config/` | Provider、默认设置、本地服务、网关等配置 |
| `agent/` | 节点预设 |
| `memories/` 或自定义记忆根目录 | Graph / 节点配置、聊天、归档、长期记忆及节点会话 |
| `.auth/` | 本机密钥、账号和设备身份 |
| `.cache/` | 本机路径设置、技能来源和派生缓存 |
| `.runtime/`、`logs/` | 启动、进程和运行诊断日志 |

切换 Memories Directory 后需要重启，配置路径不会替你迁移旧数据。服务器监听与代理修改也应重启。用启动器管理的实例可使用界面的重启入口或 `Restart.bat` / `Restart.sh`；手动前台运行时可结束进程，再使用同一解释器重启。

## 9. 常见阻塞

| 现象 | 先检查什么 |
| --- | --- |
| 网页打不开 | 前端是否构建成功、后端是否仍运行、实际监听端口；Windows 查看 `.runtime/agentpark-server.err.log` |
| 没有 Settings 或某些工具 | 是否从本机回环地址访问；远程身份与 Developer 权限；见[权限](settings/access-gateway.md) |
| Provider 报 Key missing / 401 | 密钥引用是否存在、是否选对账号、授权是否有效；不要把真实 Key 写进配置字段 |
| 模型无效 / 协议参数不支持 | Type、Base URL、Model 与 Responses 等设置是否匹配；查看提供商测试结果 |
| 第一次对话可用，后台记忆报错 | 压缩/提取/合成预设是否都引用已授权的 Provider 和明确模型 |
| Harness 节点不能执行 | 在 Harness 页检查版本、路径、安装作业输出、原生登录和权限限制 |
| 知识库搜不到 | 是否已扫描、是否有已发布文档、失败原因；Agent 还需选 Skill 并获准读取该库 |

离线检查（示例使用 Windows 虚拟环境）：

```powershell
.\.venv\Scripts\python.exe -m src.cli doctor --json
```

更多排查见 [Troubleshooting](troubleshooting.md)；全部 Settings 入口和每个字段的说明见 [逐项手册](settings/README.md)。
