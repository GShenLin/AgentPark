import os

from . import runtime_paths
from .service_host import HostBoundService
from .shared import HTTPException


class PromptLibrary(HostBoundService):
    def list_prompts(self):
        config_dir = os.path.join(runtime_paths._get_runtime_root(), "config")
        if not os.path.exists(config_dir):
            return {"prompts": []}
        files = [f for f in os.listdir(config_dir) if f.endswith(".txt")]
        return {"prompts": files}

    def get_prompt(self, filename: str):
        config_dir = os.path.join(runtime_paths._get_runtime_root(), "config")
        file_path = os.path.join(config_dir, filename)
        if not os.path.exists(file_path):
            file_path = os.path.join(config_dir, f"{filename}.txt")
            if not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="Prompt file not found")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return {"content": content}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def save_prompt(self, payload: dict):
        filename = (payload or {}).get("filename")
        content = (payload or {}).get("content")

        if not filename or not content:
            raise HTTPException(status_code=400, detail="filename and content are required")

        if not filename.endswith(".txt"):
            filename += ".txt"

        config_dir = os.path.join(runtime_paths._get_runtime_root(), "config")
        os.makedirs(config_dir, exist_ok=True)
        file_path = os.path.join(config_dir, filename)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "filename": filename}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
