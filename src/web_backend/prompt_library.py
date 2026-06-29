import os

from . import runtime_paths
from .service_host import HostBoundService
from .shared import HTTPException


class PromptLibrary(HostBoundService):
    def _prompt_dir(self):
        return os.path.join(runtime_paths._get_runtime_root(), "prompt")

    def list_prompts(self):
        prompt_dir = self._prompt_dir()
        if not os.path.exists(prompt_dir):
            return {"prompts": []}
        files = [f for f in os.listdir(prompt_dir) if f.endswith(".txt")]
        return {"prompts": files}

    def get_prompt(self, filename: str):
        prompt_dir = self._prompt_dir()
        file_path = os.path.join(prompt_dir, filename)
        if not os.path.exists(file_path):
            file_path = os.path.join(prompt_dir, f"{filename}.txt")
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

        prompt_dir = self._prompt_dir()
        os.makedirs(prompt_dir, exist_ok=True)
        file_path = os.path.join(prompt_dir, filename)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "filename": filename}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
