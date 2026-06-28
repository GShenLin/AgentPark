def build_working_path_prompt(working_path: object) -> str:
    path = str(working_path or "").strip()
    if not path:
        return ""
    return (
        f"节点工作路径: {path}\n"
        "请将此路径作为当前节点的工作目录上下文；涉及读写文件、运行命令或解释相对路径时优先基于该目录。"
    )
