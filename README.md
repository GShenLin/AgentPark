# AgentPark

[English](./README.md) | [中文](./README.zh.md)

AgentPark is an Agent platform for building, running, and sharing Agents, tools, and Graph workflows. It starts from a local-first workspace, but its product direction is broader: make Agents reusable, make tools explicit, and make Graphs portable enough to become shared automation assets instead of one-off local experiments.

The backend uses FastAPI to manage nodes, graph execution, providers, files, settings, and runtime state. The frontend uses Vue 3 + Vite to provide visual graph editing, node execution controls, memory browsing, file operations, desktop settings, and a mobile-first workspace for phone access.

## Project Goal

AgentPark aims to become a practical Agent creation and sharing platform:

- Agents should be configurable runtime units with memory, provider settings, tools, skills, plugins, and clear execution history.
- Tools should be structured capabilities that can be discovered, tested, reused, and shared across Agents and Graphs.
- Graphs should describe complete workflows, including triggers, routing, generation nodes, external channels, and recoverable runtime state.
- Local development should remain first-class, while the project moves toward cleaner packaging, portable assets, and shareable Agent/Tool/Graph libraries.
- Platform boundaries should stay explicit: node contracts, provider capabilities, runtime state, tool-call protocols, and UI/API contracts should be visible instead of hidden behind fragile fallback behavior.

## Outlook

The long-term direction is an AgentPark-style ecosystem: users can design Agents visually, connect them into Graphs, attach reusable tools and skills, then publish or exchange those assets with other users. The current project already provides the local runtime, visual editor, provider integrations, mobile access, CLI recovery path, and node/tool/plugin foundations needed for that direction. Future work should continue to turn these foundations into stable sharing formats, stronger capability metadata, safer runtime recovery, and easier distribution.

## Key Features

- Visual Graph/Node workflows: create nodes, connect ports, save complete Graph workflows, and start the Graph Runner.
- Agent execution: streaming output, tool calls, tool-call history, persistent node memory, and stop/cancel controls.
- Provider integrations: Doubao, Gemini, OpenAI-compatible APIs, Zhipu, Hyper3D, and provider capability metadata.
- Multimodal generation nodes: image generation, video generation, person-replacement video generation, 3D model generation, and 3D texture generation.
- Local tool system: Python tools under `functions/` are loaded as structured, reusable capabilities for Agent nodes.
- Sharing-oriented asset model: Agents, tools, skills, plugins, and Graphs are treated as project assets that can evolve toward portable exchange formats.
- File and resource management: the WebUI can browse, read, write, upload, and expose generated resources through `/memories`.
- Desktop settings entry: the top-right `Settings` button opens the settings UI directly, including providers, defaults, companion settings, and provider limit tests.
- Mobile support: screens up to 760px automatically use the mobile workspace, with phone-friendly PC/graph/node navigation, chat, streaming responses, attachments, node config, restart, graph editing, and settings access.
- Remote access: remote endpoint management and mobile APIs make it possible to operate workflows from another device on the same network.
- Channel nodes: receiver/sender nodes for external channels such as OpenClaw Weixin.

## Node Feature List

Node implementations live in `nodes/`. The backend exposes node metadata through `GET /api/nodes` and node templates through `GET /api/nodes/{type_id}/template`, including schema, port counts, input/output capabilities, and runtime declarations. A node `type_id` is usually the node filename without `.py`; for example, `nodes/agent_node.py` is exposed as `agent_node`.

All nodes inherit these common configuration fields:

- `skills`: load Skill documents and scripts from `skills/` for the current node.
- `plugins`: load project plugin capabilities for the current node.
- `working_path`: the directory opened by the file browser when the node is selected; Agent and command nodes also use it as working-directory context.

### Agent and Automation Nodes

| Node      | `type_id`        | Features                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent     | `agent_node`     | General-purpose LLM Agent node. Accepts text, images, videos, audio, documents, files, URLs, structured data, and meta input. Outputs text, generated image/video resources, structured data, tool calls, and meta. Supports `provider_id`, `mode`, `system_prompt`, local `tools`, `mcp_servers`, `skills`, and `plugins`. Provider capabilities can enable `web_search`, `thinking`, and `reasoning_effort`. Runtime behavior includes persistent node memory, streaming messages, tool-call history, and stop control. |
| GUI Agent | `gui_agent_node` | Single-node GUI automation loop. Captures screenshots, asks a visual/multimodal provider to plan actions, executes mouse/keyboard/scroll operations, and can verify completion. Supports `instruction`, planner/verify prompts, screenshot regions, dry run, mock actions, planner timeout, and verify timeout. Useful for local desktop or remote GUI operations.                                                                                                                                                        |

### Generation Nodes

| Node                        | `type_id`                       | Features                                                                                                                                                                                                                                                                                                                                                                                                                 |
| --------------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Image Generation            | `image_generation_node`         | Generates images from a prompt and optional reference images. Supports `aspect_ratio`, `image_size`, `response_format`, `watermark`, and `filename_prefix`. Outputs image resources and structured generation metadata. The selected provider must declare `image_generation` support in `supportmode`.                                                                                                                  |
| Video Generation            | `video_generation_node`         | Generates video from text, first/last frame images, reference images, reference video, and reference audio. Supports resolution, aspect ratio, duration, seed, generated audio, watermark, returning the last frame, callbacks, task expiration, safety identifier, web search, public base URL, and output filename prefix. Outputs video resources, optional last-frame image resources, and structured task metadata. |
| Video Change Person         | `video_change_person_node`      | Uses Wan Animate Mix-style providers to replace the subject in a reference video with a portrait image. Requires one portrait image and one reference video. Supports `wan-std`/`wan-pro`, watermark, image checking, public base URL, and output filename prefix. Outputs the replaced-person video resource and task metadata.                                                                                         |
| 3D Model Generation         | `model_generation_node`         | Uses Hyper3D/Rodin-style providers for text-to-3D or image-to-3D generation. Supports multiple reference images, Gen-2/Regular tier, alpha handling, seed, export format, material type, quality, face-count override, T/A pose, bounding-box dimensions, Raw/Quad mesh, HighPack, preview rendering, and high-definition textures. Outputs downloaded model file resources and task metadata.                           |
| 3D Model Texture Generation | `model_texture_generation_node` | Generates or repaints textures for an existing 3D model. Accepts a model file or URL, reference images, and optional prompt. Supports seed, reference scale, export format, material, and resolution. Outputs a retextured model file resource and task metadata.                                                                                                                                                        |

### Trigger, Control, and Routing Nodes

| Node            | `type_id`            | Features                                                                                                                                                                                                                                  |
| --------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BasicTrigger    | `basic_trigger_node` | Manual trigger node. Emits the configured `OutputText` when triggered. Commonly used as a workflow start point or debugging entry.                                                                                                        |
| TimerTrigger    | `timer_trigger_node` | Scheduled trigger node. Emits `OutputText` after the configured `ScheduleAt` time is reached.                                                                                                                                             |
| Clock           | `clock_node`         | Periodic trigger node. Emits `OutputText` on a day/hour/minute/second interval. Supports repeated execution and `LoopCount`, while storing current run state, next trigger time, remaining time, and trigger count.                       |
| Loop            | `loop_node`          | Loop-control node. After receiving input, output port 0 is used while the loop is still active, and output port 1 is used when the loop finishes. Supports fixed-count and infinite loops, with remaining count persisted in node config. |
| Event           | `event_node`         | Event dispatch node. Forwards the input message and adds `EventKey`, allowing downstream routing or graph-runtime dispatch by event key.                                                                                                  |
| MultiInput      | `multi_input_node`   | Multi-input aggregation node. Dynamically creates input ports from `InputCount`, caches messages from each port, waits until all ports have received input, then merges text in port order and emits it.                                  |
| InputOutputTest | `input_output_test`  | Topology test node with 3 fixed inputs and 4 fixed outputs. Useful for validating connections, port indexes, and routing behavior.                                                                                                        |

### Text, File, and Command Nodes

| Node           | `type_id`              | Features                                                                                                                                                                                                                                                |
| -------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Echo           | `echo_node`            | Echoes the input message. Optional `MyText` is used as a prefix, so output becomes `MyText + input text`.                                                                                                                                               |
| Append         | `append_node`          | Appends `AppendText` to the input text. Useful for simple prompt composition or suffix formatting.                                                                                                                                                      |
| Response       | `response_node`        | Returns a fixed response. If `MyText` is configured, it emits that value; otherwise it returns the input text. Useful as an endpoint, placeholder, or test node.                                                                                        |
| SaveFile       | `save_file_node`       | Saves input text to a file. Uses `FilePath` and optional `FileName`; when no filename is provided, it derives one from the beginning of the content, and defaults to `.md` when no extension is present. Emits the original text after saving.          |
| ConsoleCommand | `console_command_node` | Executes shell commands. If `Command` is empty, the input text is used as the command. Supports `TimeoutSeconds`, `Shell`, and node `working_path`. Has 3 output ports: stdout, stderr, and return code. Cancelling the node terminates the subprocess. |

### External Channel Nodes

| Node            | `type_id`               | Features                                                                                                                                                                                                                                                                                                                                  |
| --------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| ChannelReceiver | `channel_receiver_node` | Receives messages from external channels and forwards them downstream. The built-in channel is OpenClaw Weixin. Supports command activation through `Name`, persistent `Active` state, `AutoStart`, and polling timeout. Can forward text, structured data, files, and image resources.                                                   |
| ChannelSender   | `channel_sender_node`   | Sends upstream output back to an external channel. Currently supports OpenClaw Weixin. Configurable account, recipient, sender name, and timeout. If no explicit target is provided, it attempts to use the default target from the latest inbound message. Supports text and image resources, and emits structured send-result metadata. |

## Desktop and Mobile UI

- Desktop mode is used on wider screens and includes the full visual graph editor, topbar, remote switcher, file/memory panes, node controls, and direct `Settings` access in the top-right area.
- Mobile mode is automatically selected when the viewport is 760px wide or smaller. It provides a phone-friendly flow for selecting a PC, selecting a graph, listing nodes, chatting with a node, uploading attachments, viewing live streaming output, saving/copying/deleting messages, clearing memory, opening node configuration, creating/deleting nodes, saving/deleting graphs, restarting the workspace, and opening Settings from the header.
- Remote endpoints can be added from the desktop topbar and are stored in `config/remote.json`; mobile APIs use these endpoints to browse PCs, graphs, nodes, conversations, and messages.

## Project Layout

```text
AgentPark/
  config/              # Service config, provider config, prompt text, remote endpoints
  functions/           # Tools callable by Agent nodes
  memories/            # Graph/node memory; current memory at root, overflow archived by date
  nodes/               # Visual workflow node implementations
  scripts/             # Helper scripts
  skills/              # Agent skill documents
  src/                 # FastAPI backend, providers, protocols, runtime
  tests/               # pytest tests
  webui/               # Vue 3 + Vite frontend
```

## Requirements

- Windows is the primary target environment. Some features depend on `.bat`, PowerShell, desktop automation, or PyInstaller packaging paths.
- Linux is supported for the WebUI, CLI, provider runtime, and restart flow. Windows-only desktop and packaging features remain Windows-only.
- Python 3.11+. Windows scripts prefer local Python 3.14/3.12/3.11; Linux scripts prefer `AgentPark_Linux_env`, `.venv`, `python3`, then `python`.
- Node.js + npm for installing and building `webui`.
- ripgrep `rg` is recommended; file search tools and some frontend search paths prefer it.

## Installation

Install backend dependencies from the repository root:

```bat
python -m pip install -e .
```

Install frontend dependencies:

```bat
cd webui
npm install
```

## Configuration

Main service configuration lives in `config/config.json`:

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

- `server.host` and `server.port` control the FastAPI listen address. If the port is occupied, the startup path searches for the next available port.
- `nodeMemory.maxEntries` controls how many entries each node keeps in the current `memory.md` / `messages.jsonl`. Older entries are archived under `archive/YYYY-MM-DD/`.
- The startup graph is stored in `.cache/startup_graph.json`; this directory is not committed to Git.

Provider configuration lives in `config/moduleProvider.json`. A typical provider entry looks like this:

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

Common `type` values include `doubao`, `gemini`, `openai`, `zhipu`, and `hyper3d`. Do not commit real API keys to a public repository.

## Startup

### Build and Run

On Windows, the recommended entry is:

```bat
build_and_run.bat
```

On Linux, use:

```sh
./build_and_run.sh
```

Both platform scripts:

- Checks Python and `rg`.
- Installs missing frontend dependencies.
- Builds `webui`.
- Runs `python -m pip install -e .`.
- Starts `python -m src.fast_api --workspace-root <repo root>`.

After startup, the browser opens automatically. The default port comes from `config/config.json`; the current default is `8788`.

### Production Mode

Build the frontend static files first:

```bat
cd webui
npm install
npm run build
```

Then return to the repository root and start the backend:

```bat
cd ..
python -m src.fast_api --host 127.0.0.1 --port 8788
```

Open:

```text
http://127.0.0.1:8788/
```

To prevent automatic browser launch, add `--no-browser`:

```bat
python -m src.fast_api --host 127.0.0.1 --port 8788 --no-browser
```

### Development Mode

Start the backend:

```bat
python -m src.fast_api --host 127.0.0.1 --port 8788 --no-browser
```

Start Vite:

```bat
cd webui
npm run dev
```

Open the Vite URL:

```text
http://localhost:5173/
```

`webui/vite.config.ts` proxies frontend API requests to the backend.

### Restart

On Windows, run:

```bat
Restart.bat
```

On Linux, run:

```sh
./Restart.sh
```

The platform restart script attempts to stop the current AgentPark service, update a clean working tree, and restart through the matching build-and-run script.

The WebUI can also call `/api/system/restart` to trigger the restart flow.

## Packaging

On Windows, run:

```bat
package.bat
```

The script builds the frontend and packages the backend entry `src/fast_api.py` with PyInstaller. Output:

```text
dist/AgentPark.exe
```

After packaging, `config/`, `functions/`, and `nodes/` are copied into `dist/` as runtime resources.

## Common API Endpoints

- `GET /api/providers`: list providers.
- `GET /api/tools`: list tools under `functions/`.
- `GET /api/nodes`: list available node types.
- `GET /api/graphs`: list graphs.
- `POST /api/graphs/{graph_id}/runner/start`: start the Graph Runner.
- `POST /api/graphs/{graph_id}/emit`: send input to a graph node.
- `GET /api/nodes/instances/{node_id}/memory`: read node memory.
- `POST /api/nodes/instances/{node_id}/control`: control node runtime state.
- `POST /api/files/upload`: upload files.
- `POST /api/system/restart`: trigger service restart.
- `GET /api/settings`: list settings sections.
- `GET /api/settings/{section}`: read a settings document.
- `POST /api/settings/{section}`: update a settings document.
- `GET /api/remotes`: list remote endpoints.
- `POST /api/remotes`: add a remote endpoint.
- `DELETE /api/remotes/{remote_id}`: delete a remote endpoint.
- `GET /api/mobile/pcs`: list mobile PC entries.
- `GET /api/mobile/pcs/{pc_id}/graphs`: list graphs for mobile access.
- `GET /api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes`: list graph nodes for mobile access.
- `GET /api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes/{node_id}/conversation`: read a node conversation on mobile.
- `POST /api/mobile/pcs/{pc_id}/graphs/{graph_id}/nodes/{node_id}/messages`: send a mobile message to a node.

Full route registration lives in `src/web_backend/route_registry.py`.

## Testing

Run all tests with pytest:

```bat
python -m pytest
```

Run a single test file:

```bat
python -m pytest tests/test_node_stop_cancellation.py
```

## Development Conventions

- Add new nodes under `nodes/`; keep metadata, schema, input/output capabilities, and port declarations clear.
- Add new Agent tools under `functions/`; tool return values should stay structured and should not hide real errors.
- Put provider logic under `src/providers/`; prefer existing transport, runtime event, and tool-call protocols.
- Backend API routes are registered in `src/web_backend/route_registry.py`.
- WebUI API calls are centralized in `webui/src/api.ts`, `webui/src/uploadApi.ts`, and `webui/src/settingsApi.ts`.
- Prefer splitting files by responsibility when a single file grows beyond roughly 400 lines.

## CLI and Recovery

AgentPark also has an offline CLI for cases where FastAPI or WebUI is unavailable:

```bat
python -m src.cli chat
python -m src.cli chat --message "hello"
python -m src.cli chat --debug-terminal
python -m src.cli doctor
python -m src.cli capabilities list --graph <graph_id> --node <node_id>
python -m src.cli capabilities enable --kind skill --name <skill_id> --graph <graph_id> --node <node_id>
python -m src.cli config validate --graph <graph_id> --node <node_id>
```

`chat` starts the dedicated Companion Agent. Companion is a normal protected graph with a normal Agent node under it, using the same config fields as other nodes:

```text
memories/Companion/config.json
memories/Companion/Companion/config.json
memories/Companion/Companion/memory.md
memories/Companion/Companion/messages.jsonl
```

After the normal build/install flow, `build_and_run.bat` on Windows or `build_and_run.sh` on Linux starts the WebUI server in the background and then starts the interactive companion CLI in the current terminal. The `cli` and `chat` modes use the combined Web + CLI startup. Use `server` or `web` for WebUI only, and `cli-only` for CLI without WebUI.

The companion CLI runs the same Agent turn path as normal nodes and stores state in `memories/Companion/Companion/`. If the terminal does not accept input, run the platform build-and-run script with `cli --debug-terminal`; interactive input diagnostics fail loudly instead of silently downgrading.

Inside the companion CLI, `/restart` launches `Restart.bat` on Windows or `Restart.sh` on Linux and exits the current CLI session so restart behavior stays on the canonical startup path.

Node config reads and writes are documented in `docs/config-contract.md`. Runtime state recovery is documented in `docs/runtime-state-machine.md`. Provider feature support is documented in `docs/provider-feature-matrix.md`. Capability descriptors and dependency reporting are documented in `docs/capability-system.md`. Skill/plugin authoring is documented in `docs/skill-plugin-authoring.md`. Long-term sidecar, caching, and distribution boundaries are documented in `docs/long-term-architecture.md`. Recovery steps are documented in `docs/troubleshooting.md`.

Packaged builds expose the same offline recovery commands through the executable:

```bat
dist\AgentPark.exe doctor --json
dist\AgentPark.exe capabilities list --graph <graph_id> --node <node_id> --json
```

`package.bat` copies `docs/`, `skills/`, and `plugins/` into `dist/` so packaged doctor checks and default capability discovery use the same bundled resources as source checkout runs.
