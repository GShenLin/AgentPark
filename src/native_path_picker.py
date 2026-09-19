"""Run desktop dialogs outside the web server's address space."""
import logging
import multiprocessing


class NativePathPickerError(RuntimeError):
    pass


def _show_dialog(kind: str, initial_dir: str, initial_file: str = "") -> str:
    # GUI/IME libraries must only be imported by the dedicated child process.
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        if kind == "folder":
            return filedialog.askdirectory(parent=root, initialdir=initial_dir,
                                           title="Select folder", mustexist=True)
        return filedialog.askopenfilename(parent=root, initialdir=initial_dir,
                                          initialfile=initial_file, title="Select context file")
    finally:
        root.destroy()


def _dialog_worker(connection, kind, initial_dir, initial_file):
    try:
        selected = _show_dialog(kind, initial_dir, initial_file)
        connection.send(("ok", selected))
    except Exception as exc:
        connection.send(("error", f"{type(exc).__name__}: {exc}"[:2000]))
    finally:
        connection.close()


def select_native_path(kind: str, initial_dir: str, initial_file: str = "") -> str:
    if kind not in {"folder", "file"}:
        raise ValueError("unknown native path picker kind")
    return _run_picker(_dialog_worker, (kind, initial_dir, initial_file), timeout=300)


def _run_picker(target, arguments, *, timeout):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=target, args=(sender, *arguments), daemon=True)
    started = False
    try:
        process.start()
        started = True
        sender.close()
        logging.getLogger(__name__).info("Native path picker started: pid=%s", process.pid)
        # Wait for both the response and child exit: a crash during GUI teardown
        # must be visible instead of being mistaken for a cancelled selection.
        if not receiver.poll(timeout):
            raise NativePathPickerError("文件选择窗口超时，请重试或直接填写路径")
        try:
            result = receiver.recv()
        except EOFError as exc:
            process.join(timeout=5)
            raise NativePathPickerError(
                f"文件选择进程异常退出（exit code {process.exitcode}），请直接填写路径；后端服务仍运行"
            ) from exc
        process.join(timeout=5)
        if process.is_alive():
            raise NativePathPickerError("文件选择窗口关闭超时，请直接填写路径")
        if process.exitcode != 0:
            raise NativePathPickerError(f"文件选择进程异常退出（exit code {process.exitcode}），请直接填写路径")
        if not isinstance(result, tuple) or len(result) != 2 or not isinstance(result[1], str):
            raise NativePathPickerError("文件选择进程返回了无效结果")
        status, value = result
        if status == "error":
            raise NativePathPickerError(value)
        if status != "ok":
            raise NativePathPickerError("文件选择进程返回了未知状态")
        return value
    finally:
        if started:
            if process.is_alive():
                # Only terminate the handle created above, never discover/kill
                # processes by image name, workspace path or listener port.
                process.terminate()
                process.join(timeout=5)
            logging.getLogger(__name__).info("Native path picker exited: pid=%s code=%s", process.pid, process.exitcode)
            if not process.is_alive():
                process.close()
        receiver.close()
        sender.close()
