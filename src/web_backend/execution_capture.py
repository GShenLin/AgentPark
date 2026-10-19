"""Capture routing follows the node's actual execution device."""
from dataclasses import dataclass
from pathlib import Path
import uuid
from src.desktop_capture.contracts import CaptureRequest, CapturedFrame, DisplayCatalog
from src.desktop_capture.windows import execute_capture
from src.remote_workspace.active_execution import active_execution_context

@dataclass(frozen=True)
class ExecutionTarget:
    device_id: str
    working_path: str

class ExecutionCapture:
    def __init__(self, voice):
        self.voice = voice

    def target(self, node_id, graph_id) -> ExecutionTarget:
        path = self.voice.core.graph_runtime._node_config_path(node_id, graph_id)
        context = active_execution_context(str(Path(path).parent))
        if context is None:
            from nodes.agent_node_config import load_agent_node_run_request
            context = load_agent_node_run_request({'node_instance_id': node_id, 'graph_id': graph_id}, config_path=path)
        if not context.remote_enabled:
            return ExecutionTarget('local', '')
        if not context.remote_worker_id or not context.working_path:
            raise ValueError('节点的远程执行设备或工作目录未配置完整，无法截图。')
        return ExecutionTarget(context.remote_worker_id, context.working_path)

    def capture(self, target: ExecutionTarget, command: CaptureRequest):
        if target.device_id == 'local':
            return execute_capture(command)
        remote = self.voice.core.remote_workspace_api
        worker = remote._wait_online(target.device_id, 2)
        if 'desktop_screen' not in worker['capabilities']:
            raise RuntimeError('该执行设备尚未支持截图，请更新它的 AgentPark 或 Remote。')
        result = remote._execute({'task_id': uuid.uuid4().hex, 'worker_id': target.device_id,
                                  'tool_name': 'desktop_screen', 'working_path': target.working_path,
                                  'arguments': command.model_dump(), 'timeout_seconds': 10})
        return (DisplayCatalog if command.action == 'displays' else CapturedFrame).model_validate_json(result)
