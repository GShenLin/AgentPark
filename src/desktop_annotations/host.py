"""Own one Electron overlay via atomic local mailboxes, without a web server."""
import json
import os
import subprocess
import threading
import uuid
import time
from pathlib import Path


class AnnotationHost:
    def __init__(self, root: Path):
        self.identity = uuid.uuid4().hex
        if os.name != 'nt':
            raise RuntimeError('桌面标注目前支持 Windows。')
        executable = root / 'desktop/node-window/node_modules/electron/dist/electron.exe'
        if not executable.is_file():
            raise RuntimeError('桌面运行环境未安装，请运行 npm ci --prefix desktop/node-window。')
        env = dict(os.environ)
        env.pop('ELECTRON_RUN_AS_NODE', None)
        self._lock = threading.Lock()
        self.mailbox = root / '.runtime/annotations' / self.identity
        self.mailbox.mkdir(parents=True)
        log_path = root / '.runtime/desktop-annotations.log'
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open('ab') as log:
            self.process = subprocess.Popen(
                [str(executable), str(root / 'desktop/screen-annotations/main.cjs'),
                 f'--annotation-id={self.identity}', f'--owner-pid={os.getpid()}'],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        try:
            ready = self._receive('ready', 15)
            self.displays = ready['displays']
        except BaseException:
            self.close()
            raise

    def _receive(self, identity, timeout):
        deadline = time.monotonic() + timeout
        response = self.mailbox / 'response.json'
        while time.monotonic() < deadline:
            if response.exists():
                result = json.loads(response.read_text(encoding='utf-8'))
                if result.get('id') == 'fatal' or result.get('id') == identity:
                    if result.get('ok') is not True:
                        raise RuntimeError(result.get('error') or '桌面标注没有确认操作成功。')
                    return result
            if self.process.poll() is not None:
                raise RuntimeError('桌面标注进程已退出，请重新开启。')
            time.sleep(0.03)
        raise RuntimeError('桌面标注未在限定时间内确认，请重新开启。')

    def command(self, payload):
        with self._lock:
            identity = uuid.uuid4().hex
            try:
                temporary = self.mailbox / 'command.tmp'
                temporary.write_text(json.dumps({'id': identity, **payload}, ensure_ascii=False), encoding='utf-8')
                temporary.replace(self.mailbox / 'command.json')
                return self._receive(identity, 5)
            except (OSError, ValueError) as exc:
                raise RuntimeError(f'桌面标注连接已关闭：{exc}') from exc

    def close(self):
        # Terminate only this lease's native host, including in-flight renders.
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        for name in ('command.tmp', 'command.json', 'response.tmp', 'response.json'):
            (self.mailbox / name).unlink(missing_ok=True)
        if self.mailbox.exists():
            self.mailbox.rmdir()
