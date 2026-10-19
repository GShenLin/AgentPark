"""Stop only process trees launched and still owned by this runtime."""

import os
import signal
import subprocess


def stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        raise RuntimeError("服务进程已退出，请刷新状态")
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(f"停止服务进程树失败（退出码 {result.returncode}）：{result.stderr!r}")
    else:
        os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=30)
