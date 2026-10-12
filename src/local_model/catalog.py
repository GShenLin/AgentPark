import json
import threading
import uuid
from pathlib import Path

from src.file_transaction import atomic_write_text
from .contracts import ServiceConfig


class Catalog:
    def __init__(self, workspace: Path):
        self.path = workspace / "config" / "localModel.json"
        self.lock = threading.RLock()

    def list(self) -> list[dict]:
        with self.lock:
            if not self.path.exists():
                return []
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("services"), list):
                raise ValueError("localModel.json 格式不正确")
            return [{"id": item["id"], **ServiceConfig.model_validate(
                {k: v for k, v in item.items() if k != "id"}).model_dump()} for item in data["services"]]

    def get(self, key: str) -> dict:
        return next((item for item in self.list() if item["id"] == key), None) or self._missing(key)

    @staticmethod
    def _missing(key):
        raise KeyError(f"未找到本地服务：{key}")

    def save(self, config: ServiceConfig, key: str | None = None) -> dict:
        with self.lock:
            items = self.list()
            if key is not None:
                self.get(key)
            item = {"id": key or uuid.uuid4().hex, **config.model_dump()}
            if any(x["id"] != item["id"] and x["endpoint"] == item["endpoint"] for x in items):
                raise ValueError("该服务地址已经登记")
            items = [x for x in items if x["id"] != item["id"]] + [item]
            self._write(items)
            return item

    def remove(self, key: str):
        with self.lock:
            self.get(key)
            self._write([x for x in self.list() if x["id"] != key])

    def _write(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(str(self.path), json.dumps({"version": 1, "services": items}, ensure_ascii=False, indent=2))
