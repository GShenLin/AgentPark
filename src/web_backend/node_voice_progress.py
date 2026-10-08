"""Project public tool activity into voice progress, scoped to one request."""

TOOL_ACTIONS = {
    "execute_console_command": "运行命令", "workspace_exec": "运行工作区命令",
    "start_console_session": "启动命令", "wait_console_session": "等待命令执行",
    "read_console_session": "查看命令输出", "read_file": "读取文件",
    "rg_search_text": "搜索文件内容", "rg_list_files": "查找文件",
    "apply_patch": "修改文件", "view_image": "查看图片",
}


def voice_task_progress(live: dict) -> str:
    activities = []
    for block in live.get("activity_blocks", []):
        if block.get("type") not in {"tool_call", "web_search", "file_search"}:
            continue
        if block.get("status") not in {"running", "in_progress"}:
            continue
        label = block.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ValueError("节点工具活动缺少有效名称。")
        if block["type"] == "web_search":
            activities.append("搜索网页")
        elif block["type"] == "file_search":
            activities.append("检索文件")
        else:
            activities.append(TOOL_ACTIONS.get(label, "使用工具 " + label))
    return "正在" + "、".join(activities) if activities else ""
