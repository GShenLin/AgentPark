"""Submit one local Qwen edit, then retrieve it without holding a tool open."""
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import urlencode, urlsplit
import uuid

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from src.providers.curl_transport import CurlHttpTransport
from src.providers.curl_types import CurlHttpError

SKILL = Path(__file__).resolve().parents[1]
KIND = "agentpark.qwen-turbo-edit.v1"
MAX_BYTES = 32 * 1024 * 1024


def local_url(value):
    url = urlsplit(value)
    host = url.hostname or ""
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
    if (not loopback or url.scheme != "http" or url.username or url.password
            or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("ComfyUI URL must be a local HTTP loopback address")
    _ = url.port
    return value.rstrip("/")


def output_root():
    value = os.environ.get("AGENTPARK_NODE_DIRECTORY", "")
    node = Path(value)
    if not value or not node.is_absolute() or not node.is_dir():
        raise ValueError("AGENTPARK_NODE_DIRECTORY must be an existing absolute node directory")
    return node.resolve() / "generated_images" / "qwen_turbo"


def request(base, route, *, payload=None, body=None, content_type=None, limit=MAX_BYTES):
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        content_type = "application/json"
    response = CurlHttpTransport().request(
        url=base + route, method="POST" if body is not None else "GET",
        body=body, headers={"Content-Type": content_type} if content_type else {},
        timeout_sec=20, connect_timeout=5, follow_redirects=False,
        trust_env=False, max_response_bytes=limit,
    )
    if not 200 <= response.status_code < 300:
        response.raise_for_status()
        raise RuntimeError(f"ComfyUI HTTP {response.status_code}: {response.body[:2000]}")
    return response


def save_job(path, job):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def image_bytes(path):
    if not path.is_absolute() or not path.is_file():
        raise ValueError("image_path must be an existing absolute file path")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Input image must be between 1 byte and 32 MiB")
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as image:
        extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(image.format)
        if not extension or getattr(image, "n_frames", 1) != 1:
            raise ValueError("Expected a single-frame PNG, JPEG or WebP image")
        image.verify()
    return data, extension


def submit(args):
    prompt = args["prompt"].strip()
    resolution = args.get("resolution", 1024)
    seed = args.get("seed", secrets.randbelow(2**53))
    if not prompt or len(prompt) > 12000:
        raise ValueError("prompt must contain 1–12000 characters")
    if type(resolution) is not int or resolution not in (512, 768, 1024):
        raise ValueError("resolution must be 512, 768 or 1024")
    if type(seed) is not int or not 0 <= seed < 2**53:
        raise ValueError("seed must be an integer from 0 to 9007199254740991")
    root = output_root()
    source = Path(args["image_path"])
    data, extension = image_bytes(source)
    base = local_url(os.environ.get("AGENTPARK_COMFYUI_URL", "http://127.0.0.1:8188"))
    graph = json.loads((SKILL / "assets/edit-api.json").read_text(encoding="utf-8"))
    info = request(base, "/object_info").json()
    missing = {node["class_type"] for node in graph.values()} - info.keys()
    if missing:
        raise ValueError(f"ComfyUI is missing nodes: {sorted(missing)}")
    for node_id, parameter in (("1", "unet_name"), ("2", "clip_name"), ("3", "vae_name")):
        node = graph[node_id]
        choices = info[node["class_type"]]["input"]["required"][parameter][0]
        if node["inputs"][parameter] not in choices:
            raise ValueError(f"Required model is missing: {node['inputs'][parameter]}")
    token = uuid.uuid4().hex
    folder = root / token
    folder.mkdir(parents=True)
    filename = f"agentpark-qwen-{token}{extension}"
    boundary = "agentpark" + token
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode()
    uploaded = request(base, "/upload/image", body=body, content_type=f"multipart/form-data; boundary={boundary}").json()
    if uploaded.get("type") != "input" or not uploaded.get("name"):
        raise ValueError("ComfyUI returned an invalid uploaded image reference")
    graph["7"]["inputs"]["image"] = "/".join(filter(None, (uploaded.get("subfolder"), uploaded["name"])))
    graph["6"]["inputs"].update(prompt=prompt, resolution=resolution)
    graph["8"]["inputs"]["noise_seed"] = seed
    graph["10"]["inputs"]["filename_prefix"] = "AgentPark_Qwen_Turbo/" + token
    payload = {"prompt": graph, "client_id": token}
    (folder / "workflow-api.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    path = folder / "job.json"
    job = {"kind": KIND, "server": base, "client_id": token, "prompt_id": None,
           "status": "submission_unknown", "source_image": str(source), "seed": seed}
    save_job(path, job)
    try:
        accepted = request(base, "/prompt", payload=payload).json()
        if not accepted.get("prompt_id") or accepted.get("node_errors"):
            raise RuntimeError(f"ComfyUI rejected workflow: {accepted}")
        job.update(prompt_id=accepted["prompt_id"], status="submitted")
    except Exception as exc:
        job["error"] = str(exc)
        if isinstance(exc, CurlHttpError) and 400 <= exc.status_code < 500:
            job["status"] = "error"
    save_job(path, job)
    return {**job, "job_file": str(path)}


def result(args):
    root = output_root().resolve()
    path = Path(args["job_file"]).resolve()
    if path.name != "job.json" or path.parent.parent != root:
        raise ValueError("job_file must belong to this node's generated_images/qwen_turbo directory")
    job = json.loads(path.read_text(encoding="utf-8"))
    if job.get("kind") != KIND or job.get("client_id") != path.parent.name:
        raise ValueError("Invalid Qwen Turbo task receipt")
    base = local_url(job["server"])
    wait = args.get("wait_seconds", 30)
    if type(wait) is not int or not 0 <= wait <= 30:
        raise ValueError("wait_seconds must be an integer from 0 to 30")
    if job["status"] == "error":
        return {**job, "job_file": str(path)}
    if job["status"] == "success":
        cached = [Path(item).resolve() for item in job["image_paths"]]
        if not cached or any(item.parent != path.parent for item in cached):
            raise ValueError("Cached image paths must stay in the task directory")
        if all(item.is_file() for item in cached):
            return {**job, "job_file": str(path)}
    deadline = time.monotonic() + wait
    while True:
        pid = job["prompt_id"]
        if not pid:
            history = request(base, "/history?max_items=100").json()
            queue = request(base, "/queue").json()
            candidates = [entry["prompt"] for entry in history.values()]
            candidates += queue["queue_running"] + queue["queue_pending"]
            matches = [entry[1] for entry in candidates if entry[3].get("client_id") == job["client_id"]]
            if len(set(matches)) != 1:
                return {"status": "submission_unknown", "job_file": str(path), "error": job.get("error"),
                        "message": "Cannot uniquely recover submission; do not automatically resubmit."}
            job["prompt_id"] = pid = matches[0]
            save_job(path, job)
        history = request(base, "/history/" + str(uuid.UUID(pid))).json()
        if pid in history:
            entry = history[pid]
            status = entry["status"]
            if status["status_str"] != "success":
                return {"status": "error", "prompt_id": pid, "details": status, "job_file": str(path)}
            images = entry["outputs"].get("10", {}).get("images", [])
            if not images:
                raise RuntimeError("ComfyUI completed without a saved output image")
            images_out = []
            for index, descriptor in enumerate(images):
                if descriptor.get("type") != "output":
                    raise ValueError("Expected a ComfyUI output image")
                target = path.parent / f"result-{index + 1}.png"
                if not target.exists():
                    data = request(base, "/view?" + urlencode(descriptor)).content
                    with Image.open(io.BytesIO(data)) as image:
                        if image.format != "PNG":
                            raise ValueError("Expected PNG from SaveImage")
                        image.verify()
                    temporary = target.with_suffix(".tmp")
                    temporary.write_bytes(data)
                    temporary.replace(target)
                images_out.append(str(target))
            job.update(status="success", image_path=images_out[0], image_paths=images_out)
            save_job(path, job)
            return {**job, "job_file": str(path)}
        queue = request(base, "/queue").json()
        state = "unknown"
        for key, value in (("queue_running", "running"), ("queue_pending", "queued")):
            if any(item[1] == pid for item in queue[key]):
                state = value
        if state == "unknown":
            # It may have finished between the history and queue reads.
            if pid in request(base, "/history/" + pid).json():
                continue
        if state == "unknown" or time.monotonic() >= deadline:
            return {"status": state, "prompt_id": pid, "job_file": str(path)}
        time.sleep(min(3, max(0, deadline - time.monotonic())))


def main():
    try:
        args = json.load(sys.stdin)
        action = os.environ["AGENTPARK_SKILL_SCRIPT_ID"]
        handler = {"submit": submit, "result": result}[action]
        print(json.dumps(handler(args), ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=True), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
