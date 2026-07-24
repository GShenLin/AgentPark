from __future__ import annotations

import os

from fastapi import HTTPException

from .service_host import HostBoundService


class NodeInstanceFiles(HostBoundService):
    def list_node_instance_files(self, node_id: str, graph_id: str = "") -> dict:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        node_dir = os.path.abspath(self.graph_runtime._node_dir(safe_graph_id, safe_node_id))
        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail="node directory not found")

        files: list[dict[str, object]] = []
        try:
            for root, directories, filenames in os.walk(node_dir):
                directories.sort(key=str.casefold)
                for filename in sorted(filenames, key=str.casefold):
                    file_path = os.path.join(root, filename)
                    relative_path = os.path.relpath(file_path, node_dir).replace("\\", "/")
                    try:
                        size = os.path.getsize(file_path)
                    except OSError:
                        size = 0
                    files.append(
                        {
                            "name": filename,
                            "path": relative_path,
                            "size": size,
                        }
                    )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="node directory cannot be read") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to list node files: {exc}") from exc

        files.sort(key=lambda item: str(item["path"]).casefold())
        return {
            "graph_id": safe_graph_id,
            "node_id": safe_node_id,
            "files": files,
        }


__all__ = ["NodeInstanceFiles"]
