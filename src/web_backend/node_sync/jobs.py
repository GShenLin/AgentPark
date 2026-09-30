"""Durable orchestration on the selected host, independent of browser lifetime."""
from __future__ import annotations

import threading
import uuid

import json
from src.providers.curl_transport import CurlHttpTransport
from fastapi import HTTPException

from .blobs import read_json, write_json
from .contracts import SyncRequest, SyncConflict
from .cloud import CloudDevices


class SyncJobs:
    def __init__(self, service):
        self.service = service
        self.root = service.root / "jobs"
        self.running: set[str] = set()
        self.lock = threading.Lock()
        self.cloud = CloudDevices(service.core)

    def remotes(self, request):
        remotes = [{**r, "kind": "local" if r["id"] == "default" else "lan",
                    "address": f"{r['host']}:{r['port']}", "available": True, "state": ""}
                   for r in self.service.core.remote_api.list_remotes(request)["remotes"]]
        return {"remotes": remotes + self.cloud.remotes(request)}

    def call(self, remote_id, operation, payload, request):
        if remote_id.startswith("cloud:"):
            return self.cloud.call(remote_id, operation, payload, request)
        remotes = self.service.core.remote_api.list_remotes(request)["remotes"]
        remote = next((r for r in remotes if r["id"] == remote_id), None)
        if remote is None:
            raise SyncConflict("远端已删除或无权访问，请重新选择。")
        if remote_id == "default":
            return self.service.protocol(operation, payload, request)
        host = remote["host"]
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        url = f"http://{host}:{remote['port']}/api/node-sync/protocol/{operation}"
        headers = {k: request.headers[k] for k in ("x-agentpark-client-id", "x-agentpark-username")
                   if request and k in request.headers}
        response = CurlHttpTransport().request(url=url, method="POST",
            body=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            trust_env=False, timeout_sec=180, connect_timeout=10, follow_redirects=False)
        if response.status_code in {404, 405}:
            raise SyncConflict(f"远端 {remote['name']} 尚不支持节点同步，请更新并重启该端。")
        if response.status_code == 403:
            raise SyncConflict(f"远端 {remote['name']} 未授予当前用户开发者权限，请在该端授权设置中授权。")
        if response.status_code >= 400:
            raise SyncConflict(f"远端 {remote['name']}：HTTP {response.status_code} {response.body[:1000]}")
        if not response.headers.get("content-type", "").startswith("application/json"):
            raise SyncConflict("远端返回了非同步协议内容，请确认地址和版本。")
        return response.json()

    def path(self, job_id):
        if len(job_id) != 32 or not job_id.isalnum():
            raise SyncConflict("无效同步任务。")
        return self.root / (job_id + ".json")

    def get(self, job_id, request=None):
        job = read_json(self.path(job_id))
        if job is None:
            raise SyncConflict("同步任务不存在。")
        self.require_owner(job, request)
        with self.lock:
            active = job_id in self.running
        if not active and job["state"] in {"preparing", "applying"}:
            job = {**job, "state": "interrupted", "error": "服务重启中断了同步，可继续上次任务。"}
        return job

    def require_owner(self, job, request):
        if "cloud_owner" in job and job["cloud_owner"] != self.cloud.owner(request):
            raise HTTPException(403, "该同步任务属于另一个云端管理员会话。请重新预览当前选择。")

    def create(self, payload: SyncRequest, request):
        job = {"id": uuid.uuid4().hex, "selection": payload.model_dump(), "state": "preparing",
               "phase": "正在读取来源", "result": None, "error": "", "completed_nodes": 0}
        if any(e.remote_id.startswith("cloud:") for e in (payload.source, payload.target)):
            job["cloud_owner"] = self.cloud.owner(request)
            self.cloud.get(request)
        write_json(self.path(job["id"]), job)
        self.launch(job["id"], "preview", request)
        return self.get(job["id"], request)

    def launch(self, job_id, action, request):
        path = self.path(job_id)
        with self.lock:
            if job_id in self.running:
                return
            job = read_json(path)
            if job is None:
                raise SyncConflict("同步任务不存在。")
            self.require_owner(job, request)
            if action == "commit" and (not job.get("ticket") or job["result"]["conflicts"]):
                raise SyncConflict("请先完成无冲突的预览。")
            if job["state"] == "complete":
                return
            self.running.add(job_id)
            job["state"] = "applying" if action == "commit" else "preparing"
            job["action"] = action
            job["error"] = ""
            write_json(path, job)
        threading.Thread(target=self.run, args=(job, action, request), daemon=True,
                         name=f"node-sync-{job_id[:8]}").start()

    def run(self, job, action, request):
        path = self.path(job["id"])
        selection = SyncRequest.model_validate(job["selection"])
        source, target = selection.source, selection.target
        def save(phase):
            job["phase"] = phase
            write_json(path, job)
        def call(endpoint, op, data):
            return self.call(endpoint.remote_id, op, data, request)
        try:
            if action == "preview":
                if "export" not in job:
                    job["export"] = call(source, "export", source.model_dump(exclude={"remote_id"}))
                    write_json(path, job)
                exported = job["export"]
                if exported["version"] != 1:
                    raise SyncConflict("两端同步协议不兼容，请更新。")
                blobs = {exported["manifest"]: exported["manifest_bytes"], **exported["blobs"]}
                done = 0
                for sha, size in blobs.items():
                    status = call(target, "blob-status", {"sha": sha})
                    if status["complete"] and status["offset"] != size:
                        raise SyncConflict("目标缓存大小异常。")
                    while not status["complete"]:
                        save(f"传输消息和附件 {done + status['offset']} / {sum(blobs.values())} 字节")
                        chunk = call(source, "blob-read", {"sha": sha, "offset": status["offset"]})
                        if chunk["total"] != size:
                            raise SyncConflict("来源快照大小变化。")
                        status = call(target, "blob-write", {"sha": sha, "chunk": chunk})
                    done += size
                save("正在比较目标记忆与结构")
                result = call(target, "prepare", {"manifest": exported["manifest"],
                              "target": target.model_dump(exclude={"remote_id"})})
                job["ticket"] = result.pop("ticket")
                job["result"] = result
                job["state"] = "ready"
                save("预览完成，等待点击开始同步")
            else:
                save("正在提交 Graph 结构")
                call(target, "apply", {"ticket": job["ticket"], "index": -1})
                for index in range(job["result"]["nodes"]):
                    save(f"正在合并节点 {index + 1} / {job['result']['nodes']}")
                    call(target, "apply", {"ticket": job["ticket"], "index": index})
                    job["completed_nodes"] = index + 1
                job["state"] = "complete"
                save("同步完成")
        except Exception as exc:
            job["state"] = "failed"
            job["error"] = str(exc.detail if isinstance(exc, HTTPException) else exc)
            write_json(path, job)
        finally:
            with self.lock:
                self.running.discard(job["id"])
