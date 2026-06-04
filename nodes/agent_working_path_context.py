def build_working_path_prompt(working_path: object) -> str:
    path = str(working_path or "").strip()
    if not path:
        return ""
    return (
        f"节点工作路径: {path}\n"
        "请将此路径作为当前节点的工作目录上下文；涉及读写文件、运行命令或解释相对路径时优先基于该目录。"
    )


def prepend_working_path_context(user_content: object, working_path: object) -> object:
    prompt = build_working_path_prompt(working_path)
    if not prompt:
        return user_content

    if isinstance(user_content, str):
        return f"{prompt}\n\n{user_content}" if user_content.strip() else prompt

    if isinstance(user_content, dict):
        content_type = str(user_content.get("type") or "").strip().lower()
        text = str(user_content.get("text") or "")
        if content_type == "image" or "text" in user_content:
            return {
                **user_content,
                "text": f"{prompt}\n\n{text}".strip(),
            }
        return {
            "type": "text",
            "text": prompt,
            "payload": user_content,
        }

    if isinstance(user_content, list):
        if user_content and isinstance(user_content[0], dict) and user_content[0].get("type") == "text":
            first = dict(user_content[0])
            first["text"] = f"{prompt}\n\n{str(first.get('text') or '')}".strip()
            return [first, *user_content[1:]]
        return [{"type": "text", "text": prompt}, *user_content]

    return user_content
