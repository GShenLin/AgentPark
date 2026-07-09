import os

from .service_host import HostBoundService
from .shared import HTTPException
from src.file_transaction import atomic_write_text
from src.workspace_settings import get_workspace_root


class PromptLibrary(HostBoundService):
    _KIND_DIRS = {
        "instruction": "instruction",
        "system_prompt": "prompt",
    }

    def _prompt_dir(self, kind: object):
        prompt_kind = self._validate_kind(kind)
        return os.path.join(get_workspace_root(), self._KIND_DIRS[prompt_kind])

    def list_prompts(self, kind: str):
        prompt_dir = self._prompt_dir(kind)
        if not os.path.exists(prompt_dir):
            return {"prompts": []}
        files = [f for f in os.listdir(prompt_dir) if f.endswith(".txt") and os.path.isfile(os.path.join(prompt_dir, f))]
        return {"prompts": files}

    def get_prompt(self, filename: str, kind: str):
        prompt_dir = self._prompt_dir(kind)
        file_path = self._resolve_prompt_path(prompt_dir, filename)
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
        kind = (payload or {}).get("kind")

        if not filename or content is None or not kind:
            raise HTTPException(status_code=400, detail="kind, filename, and content are required")

        prompt_dir = self._prompt_dir(kind)
        os.makedirs(prompt_dir, exist_ok=True)
        file_path = self._resolve_prompt_path(prompt_dir, filename)

        try:
            atomic_write_text(file_path, str(content))
            return {"ok": True, "filename": os.path.basename(file_path)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def _validate_kind(self, kind: object) -> str:
        if not isinstance(kind, str):
            raise HTTPException(status_code=400, detail="invalid prompt kind")
        prompt_kind = kind.strip()
        if prompt_kind not in self._KIND_DIRS:
            raise HTTPException(status_code=400, detail="invalid prompt kind")
        return prompt_kind

    def _resolve_prompt_path(self, prompt_dir: str, filename: object) -> str:
        raw = str(filename or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="filename is required")
        name = raw if raw.lower().endswith(".txt") else f"{raw}.txt"
        if name != os.path.basename(name) or name in {".txt", "..txt"}:
            raise HTTPException(status_code=400, detail="invalid prompt filename")
        return os.path.join(prompt_dir, name)
