"""Route overlay operations to the same explicit execution target as screen capture."""
import logging
import threading
import uuid

from src.desktop_annotations.execution import (
    ExecutionAnnotationCommand, ExecutionAnnotationResult, execution_annotations,
)

log = logging.getLogger(__name__)


class ExecutionAnnotationHost:
    def __init__(self, voice, target):
        self.voice, self.target = voice, target
        self.closed = False
        self.identity = None
        result = self.execute(ExecutionAnnotationCommand(action='prepare'))
        self.identity = result.annotation_id
        self.displays = [d.model_dump() for d in result.displays]

    def execute(self, command):
        if self.target.device_id == 'local':
            return execution_annotations.execute(command)
        remote = self.voice.core.remote_workspace_api
        worker = remote._wait_online(self.target.device_id, 2)
        if 'desktop_annotations' not in worker['capabilities']:
            raise RuntimeError('该执行设备尚未支持桌面标注，请更新该设备的 AgentPark。')
        result = remote._execute({'task_id': uuid.uuid4().hex, 'worker_id': self.target.device_id,
            'tool_name': 'desktop_annotations', 'working_path': self.target.working_path,
            'arguments': command.model_dump(exclude_none=True), 'timeout_seconds': 20})
        return ExecutionAnnotationResult.model_validate_json(result)

    def command(self, payload):
        if self.closed:
            raise RuntimeError('桌面标注已关闭，请重新开启。')
        result = self.execute(ExecutionAnnotationCommand.model_validate(payload))
        if result.annotation_id != self.identity:
            raise RuntimeError('执行端返回了不匹配的标注会话。')
        return result.model_dump()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.target.device_id == 'local':
            self.execute(ExecutionAnnotationCommand(action='stop', annotation_id=self.identity))
        else:
            # Lease cleanup holds the voice lock; remote RPC must run outside it.
            # The execution process owns the native host; browser status polling
            # is not a lease that can terminate it on a transient network delay.
            def stop():
                try:
                    self.execute(ExecutionAnnotationCommand(action='stop', annotation_id=self.identity))
                except Exception:
                    log.exception('Failed to stop execution annotation %s on %s', self.identity, self.target.device_id)
            threading.Thread(target=stop, name='annotation-stop', daemon=True).start()
