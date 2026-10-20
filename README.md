# AgentPark

[English](./README.md) | [中文](./README.zh.md)

AgentPark is a visual Agent workspace that runs on your own machine and is accessed through a browser. Start by chatting with one Agent, then organize multiple Agents, tools, and triggers into workflows or collaboration groups. Each Agent uses its own model, working directory, capabilities, and history to carry out tasks.

**The project's main strength is bringing different models and Agent runtimes onto one board where you can follow their work, coordinate them, and use them across devices.** Standard Agent, Codex, Claude Code, and other nodes can work on the same task. You can inspect progress, adjust responsibilities, review tool calls, and keep a separate conversation for each node.

This guide introduces the features available in the current code, from the basics to advanced use. If this is your first time, continue with **[GettingStart: installation, configuration, and your first conversation](docs/GettingStart.md)**. For a complete settings reference, see the **[Settings manual](docs/settings/README.md)**.

<img width="1920" height="911" alt="AgentPark screenshot" src="https://github.com/user-attachments/assets/1f93e6e6-5b29-4001-9364-2e8e54395b36" />

## Why Use AgentPark?

| Highlight | What you can do |
| --- | --- |
| Organize work visually | Create nodes, connections, and groups in Graph / Board, open node chats directly, and check runtime status |
| Multiple Agent runtimes | Use AgentPark's own Agent or connect one of nine Harnesses; each runtime retains its own tools, sessions, and permission rules |
| Clear responsibilities for each member | Collaboration groups share goals, tasks, dependencies, and handoff updates while members keep their own models and histories |
| Lasting node context | Standard Agents support history compaction and node-level long-term memory; summaries include sources so you can retrieve the original evidence |
| Verifiable local information | Folder knowledge bases support PDF, text, Word, and Excel, with checkable sources for search results and spreadsheet calculations |
| Access beyond your computer | Dedicated entry points for the mobile browser workspace, Windows node windows, device center, remote execution, and node synchronization |
| Traceable execution | End-to-end audits, tool success rates, failure details, Provider queues, and usage help you diagnose problems |

<img width="1920" height="911" alt="AgentPark screenshot" src="https://github.com/user-attachments/assets/97dce8df-69a3-4531-af14-012d67884f1f" />

## Start the Project

Run AgentPark from the source directory. You will need Git, Python with pip (3.12 is recommended to start), and Node.js/npm. Use a supported LTS version of Node.js that meets the requirements: the WebUI and Windows node windows require Node.js 22.12 or later, and some Harnesses require a newer version. You must configure your own model-service accounts or API keys.

On Windows, run this in PowerShell from the project root:

```powershell
.\build_and_run.bat
```

On Linux / macOS, run this from the project root:

```sh
sh ./build_and_run.sh server
```

Open the [local workspace](http://127.0.0.1:8766). The application listens on `0.0.0.0:8766` by default. Configuration or an occupied port may change the actual port; check the startup log. For initial configuration, access Settings through the local loopback address.

The startup scripts install dependencies, build the WebUI, and start the backend. The Windows entry point also prepares node windows, checks for repository updates and private CA trust, and attempts to publish the cloud frontend. See [GettingStart](docs/GettingStart.md) for the details, manual startup steps, and the configuration sequence if you do not yet have an account. A successful startup means the service is available; model tasks still require a valid Provider, model, and authorization.

The shortest path to your first run:

1. Open **Settings → Model Providers** and configure the connection URL, key or official authorization, and model list.
2. Right-click an empty area of the board to create an **Agent**, select a Provider and a specific model, and send a simple question first.
3. Configure reusable models, instructions, and capabilities in **Node Presets**, then select the relevant presets under **Companion / Default Settings**.
4. Add a knowledge base when you need to read source material. When you need a coding runtime, install its CLI under Harness.

## Stage 1: Get Started with a Single Node

### 1. Boards and Node Management

A Graph is a workspace containing nodes, connections, and groups; the Board is its visual interface. You can create and switch Graphs, drag nodes, adjust layouts, edit node names and annotations, and open node configuration and chat. Use separate Graphs to manage different tasks.

Each node has its own runtime state and task queue. Send messages through the input box and use node controls to trigger, pause, or stop work. When viewing a final response, you can also expand the process to inspect model output and tool execution. The meaning of pause and stop depends on the node's current state and the feedback from its controls.

### 2. Chat with a Standard Agent

An `Agent` node uses AgentPark's runtime. Depending on the selected Provider's actual capabilities, it can chat, understand images, call tools, and work with resources. The input box accepts text and attachments, and chat and process records are persisted in the node directory.

Model selection has two parts: **Provider + Model**. The Provider determines the connection, authorization, and protocol; the Model specifies which model to request. Do not use a Provider ID as a model name. See [Models and Harnesses](docs/settings/models.md) for configuration details.

### 3. Files and Attachments

Use the file panel to browse workspace resources. In a node or group input box, select, drag and drop, or paste attachments that the browser can read. Images can be previewed, and files can be passed to the model as resources. Whether a model can directly understand a particular format depends on the node and Provider. The browser file panel's workspace boundary and the Agent's file-tool permissions are separate boundaries.

### 4. Reuse Node Presets

An Agent Profile / Preset saves the node type, model, instructions, capabilities, and event rules. Use presets to repeatedly create roles such as researcher, programmer, or reviewer. Once you have created and tested a node, save it as a preset and edit it in **Settings → Node Presets**.

Standard nodes copy a preset's configuration when they are created. Companion and background reasoning configurations instead read presets by ID. Changing a preset has different effects in these cases; see [Node Presets and Companion](docs/settings/presets-companion.md).

### 5. Companion and the Command Line

Companion is the workspace's companion Agent. Select its preset and local working directory in Settings; the preset determines its model, instructions, and capabilities. Windows startup repair also uses this preset.

The command line also supports chat and offline diagnostics:

```powershell
python -m src.cli chat
python -m src.cli doctor --json
```

Both commands require a Python environment with the project's dependencies installed. `chat` also requires a working Companion configuration.

## Stage 2: Give Agents Knowledge and Tools

### 6. Multiple Providers and Account Management

The settings form includes types for OpenAI, Claude, DeepSeek, Doubao, Gemini, Grok, Kimi, Zhipu, Hyper3D, Agnes, and local alpha matting. Adapter capabilities vary; selecting a capability checkbox cannot make a service support a protocol it does not implement.

You can manage API key references, named accounts, multiple OAuth accounts, and pinned accounts. Secrets are stored in `.auth/`; Provider configurations reference key names or account IDs. Official OAuth entry points are available only for types that implement the protocol. See [Model Connections and Authorization](docs/settings/models.md).

### 7. Tools, Skills, MCP, and Plugins

| Capability | Purpose | How to enable it |
| --- | --- | --- |
| Tool | Callable functions for files, commands, node operations, and more | Select tools in the node configuration |
| Skill | A task workflow with instructions, scripts, and resources | Select a Skill on the node; the runtime activates it as needed |
| MCP | Connect a local subprocess or remote MCP service | Register the service in Default Settings, then select it on the node |
| Plugin | Organize extensions through a plugin manifest | Install the corresponding resources and select the plugin on the node |

Skill management brings together project, system-user, and custom sources. You can search, read instructions, inspect dependencies and references, organize folders, move items to the recycle area, and restore them. Capability changes are normally loaded on the next Agent execution; they do not automatically restart a running task. See [Skills and Extensions](docs/settings/skills.md).

### 8. Local Folder Knowledge Bases

Knowledge bases recursively scan PDF, Markdown, TXT, DOCX/DOC, and XLSX/XLS files. They use an OpenAI-compatible text embedding service to build an on-disk index with keyword, semantic, and hybrid search. You can scan incrementally, pause, resume, retry failed files, and test search results on the management page.

With the `knowledge` Skill selected, an Agent can list documents, search, read source text, and calculate statistics for specified Excel worksheets and row ranges within authorized knowledge bases. Results identify PDF pages, text lines, Word paragraphs, or Excel rows and columns. OCR is not currently performed; DOC files require LibreOffice, and formulas use the calculated values saved in the file. See the [Knowledge Base Guide](docs/settings/knowledge.md).

### 9. Conversation Compaction and Node Long-Term Memory

When a standard Agent's ongoing conversation exceeds its history budget, older content can be compacted in the background while recent messages are kept verbatim. Long-term memory extracts and synthesizes short summaries from the node's completed task history, injects them into later inputs, and retrieves sources as needed.

The two features have separate reasoning presets, budgets, and processing thresholds. Each node maintains its own memory. Tools are also available to explicitly remember information, correct it, or forget it by source. See [Default Settings](docs/settings/defaults.md) for the differences between history compaction, long-term memory, and clearing chat.

### 10. Commands and Process Sessions

The built-in Agent's `system_tools` support short synchronous commands and starting, reading, waiting for, and stopping asynchronous process sessions. For builds or tests, you can read output incrementally and cancel execution. Commands use the platform and shell declared by the backend: PowerShell on Windows and the detected shell on POSIX systems. Sessions belong to the current Agent execution and cannot be resumed across turns or restarts. See [Command Sessions](docs/console-sessions.md).

### 11. Browser and Windows Desktop Operations

Browser automation is available through the corresponding Skills and dependencies. Windows `computer-use` supports window discovery, screenshots, UI Automation, and mouse and keyboard operations. Choose a model that supports image input and tool calls, and install the dependencies required by the Skill. Desktop capabilities require a Windows graphical session and cannot be used directly on a Linux backend. See [Computer Use](docs/computer-use.md).

### 12. Local Service Management

In **Settings → Local Services**, register any local service and configure its startup program, working directory, arguments, service URL, and health checks. You can start, stop, and check services manually. The Strata and ComfyUI management presets also provide model discovery and related operations.

Registering a service does not connect it as a model Provider or automatically download or load model weights. See [Local Services](docs/settings/local-services.md) for ordinary services and the two management presets.

## Stage 3: Workflows, Multiple Agents, and Multimodal Tasks

### 13. Workflows with Connected Nodes

Connect output ports to input ports to pass upstream results to downstream nodes. This lets you split input preparation, model processing, and file output into steps that can be inspected individually.

| Node | Implemented behavior |
| --- | --- |
| BasicTrigger | Trigger manually and send configured text |
| TimerTrigger / Clock | Trigger at a specified time / emit output at a fixed interval |
| Append / Response / Echo | Append fixed text / return configured text / echo input |
| MultiInput | Wait for all input ports, then merge in port order |
| Loop | Run the loop branch a specified number of times, then take the exit |
| Event | Dispatch input by EventKey |
| ConsoleCommand / SaveFile | Execute a configured command / write input to a file |

Validate a small workflow with a trigger, one Agent, and an output node before adding branches and loops. Scheduled triggers require the backend to be running; they are not equivalent to an operating-system service that runs continuously.

### 14. Multi-Agent Collaboration Groups

Box-select multiple Agents and press **G** to create a group, then edit its shared goal, member responsibilities, and tasks. Tasks can specify an assignee, prerequisite dependencies, status, and verification evidence. Members can hand off work to specific members, waking only those involved. Shared activity, task replies, and archived tasks help track progress.

The group itself does not use a model. Each node retains its own model, tools, and history. Groups suit tasks with clear responsibilities, such as “research → implementation → verification.” See the [Collaboration Group Guide](docs/agent-groups-guide.md) for the full workflow.

### 15. Nine Harnesses

The currently registered Harnesses are **Codex, Claude Code, OpenClaw, DeepSeek Harness, MiniMax Code, OpenCode CLI, Antigravity CLI, Pi, and Hermes Agent**. Check, install, upgrade, or uninstall them in Settings, then create nodes of the corresponding type.

OpenCode and Antigravity use their native model catalogs. Provider binding, login, tools, and permissions for the other nodes depend on their respective adapters. Harnesses do not automatically gain all the Skills and background memory capabilities of standard Agents, and not every native interactive approval can necessarily be handled during headless execution. See [Using Harnesses](docs/settings/models.md#harness).

### 16. Images, Video, 3D, and Audio

Available Agent fields are shown dynamically according to the Provider's `supportmode`, supporting image generation and editing, image understanding, video generation, and audio generation. Background removal, video subject replacement, 3D generation, and texturing use dedicated nodes. Image attachments can also serve as multimodal chat input.

The voice-related code also includes service-configured capabilities for transcription, TTS, real-time interaction, and simultaneous interpretation. Doubao audio and RTC require the appropriate speech keys, AK/SK, or application configuration. Whether a feature runs depends on the service, model, account quota, and local dependencies. See the [Model Manual](docs/settings/models.md) for configuration and [OpenAI Images](docs/openai-image-provider.md) for image API details.

### 17. Messaging Channels and Scheduled Wake-Ups

Channel receiver/sender nodes can bring WeChat channel messages into a Graph and send replies from node output. You must sign in to the channel and configure its receiver node. Scheduled node wake-ups use the project's cron capabilities and are separate from TimerTrigger / Clock triggers within a Graph. The backend, channel account, and target node must all be available.

## Stage 4: Across Interfaces and Devices

### 18. Mobile Access and Standalone Node Windows

The browser provides a mobile workspace based on screen size, with access to nodes, chats, attachments, and collaboration groups. On a local Windows machine, right-click a node and choose “Pop out node” to continue chatting in an always-on-top window. It can keep using the running backend after the main webpage is closed. Closing the window does not delete the node or stop its task. See [Standalone Node Windows](docs/node-windows.md).

### 19. Device Connectivity and the Cloud Device Center

Devices approved by the authentication center can connect through WebRTC, preferring direct connections and using TURN relays when needed. Application data is end-to-end encrypted. Administrators can open a device's Board from the cloud device center.

Two backends can also explicitly grant viewing, control, and Agent collaboration permissions for public Graphs, and send targeted messages through `peer_network_tools`. Approval for a device to come online and granting application-level permissions between the two sides are separate steps. See [Devices and Synchronization](docs/settings/connectivity.md).

### 20. Remote Execution and Cross-Device Workspaces

A registered Remote or AgentPark instance can act as an execution device. Right-click a node and choose a device through **LinkToRemote** to perform supported file and command operations using the remote workspace protocol. The remote working directory, platform, shell, and tool capabilities determine the actual execution environment. This is different from opening a remote Board. For Linux worker deployment, see [Remote Worker](deploy/remote-worker/README-linux.md).

### 21. Incremental Node and Whole-Graph Synchronization

Select source and target nodes to synchronize user messages, final responses, attachments, and Archive content. If neither side has a node selected, synchronization covers the Graph structure and each node's conversation. The preview shows messages, attachments, structural changes, and conflicts; confirm it before applying the changes.

Synchronization preserves extra content already present at the destination. It does not propagate deletions, transfer Process records, copy model accounts or plugin installations, or automatically execute tasks. See [Node Synchronization Steps](docs/settings/connectivity.md#node-sync).

## Stage 5: Advanced Configuration and Maintenance

### 22. Runtime Events

Configure handling rules for input, tool failures, runtime prompts, network errors, persisted results, and task failures. Rules can generate context, append to files, write notifications, or hand work to an Agent. You can adjust context TTL, snippet length, and the deduplication window, and inspect compilation diagnostics. See [Runtime Events and Themes](docs/settings/events-theme.md).

### 23. Public Model Gateway

Expose selected models from local Providers through a gateway. Manage separate gateway keys, pinned accounts, and allowed protocols, with built-in request testing and usage statistics by date, IP, and model. Supported endpoints include Models, Responses, Chat Completions, Messages, and JSON-based image generation/editing. Both the upstream service and the gateway must allow the protocol. See [Permissions and Gateway](docs/settings/access-gateway.md).

### 24. Permissions and Visibility

Manage remote usernames, client/IP records, Developer identities, and tool filtering for non-Developers. Providers can be private; device sharing has its own authorization, and the cloud administrator Board has a separate owner identity. Identify which access entry point you are using before configuring permissions. See [Authorization](docs/settings/access-gateway.md#authorization).

### 25. Provider Testing and Load Monitoring

**Provider Testing** queries models and probes actual API capabilities, distinguishing unsupported features from inconclusive results. The **Pressure** page displays runtime concurrency, queues, RPM/TPM usage, and peaks. It is a monitoring page; opening it does not automatically start a load test. See the [Diagnostics Manual](docs/settings/diagnostics.md).

### 26. End-to-End Auditing and Tool Statistics

Select a run by date, Graph, and node to inspect its input, model turns, tool results, file changes, and timeline. View success rates, failure reasons, and token usage by Provider. When the server does not return usage data, it is shown as missing rather than counted as zero. See [Statistics and Auditing](docs/settings/diagnostics.md#statistics).

### 27. Appearance, Storage, and Lifecycle

Adjust theme presets, panel colors and background images, Agent popup and board sizes, undo depth, proxies, the service's listening address, and the memory directory. There are controls to clear logs, clear derived long-term memory, and shut down the backend. Startup and restart preserve logs and restore state as implemented; they do not guarantee recovery of every external process or native CLI session. See [Default Settings](docs/settings/defaults.md) and [Maintenance](docs/settings/diagnostics.md#maintenance).

### 28. Execution Records and Whole-Session Checkpoints

AgentPark's own Responses execution path can enable a node-level step ledger to record requests, tool starts/finishes, and responses. After a process interruption, tool results without a completion record are marked as unknown, prompting a check of external state first. It can also generate whole-session checkpoints in response to model context-window pressure, retaining recent conversation and original records so long tasks can continue.

These features must be explicitly enabled in the Provider's advanced JSON. They operate separately from background history summaries and long-term memory. See [Advanced Model Settings](docs/settings/models.md#高级-json执行记录与整会话压缩) for fields, defaults, and recovery boundaries.

## Documentation and Development

| Your goal | Where to start |
| --- | --- |
| Install and complete your first conversation | [GettingStart](docs/GettingStart.md) |
| Find fields and steps by Settings menu | [Settings Manual](docs/settings/README.md) |
| Find topic guides and technical documentation | [Docs Index](docs/README.md) |
| Extend Skills / plugins | [Capability System](docs/capability-system.md), [Authoring Guide](docs/skill-plugin-authoring.md) |
| Understand code boundaries | [Architecture Overview](docs/architecture/agentpark-architecture-overview.md), [Configuration Contract](docs/config-contract.md) |
| Diagnose startup and configuration issues | [Troubleshooting](docs/troubleshooting.md), [Startup Repair](docs/startup-repair.md) |

The backend uses Python / FastAPI, and the frontend uses Vue 3 / TypeScript / Vite. See [AGENTS.md](AGENTS.md) for development constraints. The project is licensed under [MIT](LICENSE). Feature descriptions reflect the repository's current implementation; available models, quotas, and external software support depend on actual service queries and runtime results.
