import math
import logging
import time
import re
from pathlib import Path

import httpx

from src.provider_api_key_store import api_key_store_path, load_api_key_store

from .contracts import LibraryConfig
from .scanner import Interrupted, check_stop


MAX_RATE_LIMIT_RETRIES = 3


def rate_limit_code(response):
    """Log only a bounded machine code; upstream messages may echo input/secrets."""
    try:
        payload = response.json()
    except ValueError:
        return "unavailable"
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code) else "unavailable"


class EmbeddingError(RuntimeError):
    pass


class Embedder:
    def __init__(self, config: LibraryConfig, *, workspace: Path | None = None, stop=None):
        self.config = config
        self.workspace = workspace
        self.stop = stop

    def resolve_key(self) -> str:
        if not self.config.api_key_alias:
            return ""
        if self.workspace is None:
            raise EmbeddingError("解析 API Key Name 需要工作区路径")
        try:
            keys = load_api_key_store(api_key_store_path(str(self.workspace)))
        except (OSError, ValueError) as exc:
            raise EmbeddingError("无法读取共享 API Key 存储，请在 API Key Name 中选择或添加密钥") from exc
        if self.config.api_key_alias not in keys:
            raise EmbeddingError(f"API Key Name 不存在：{self.config.api_key_alias}，请重新选择或添加")
        return keys[self.config.api_key_alias]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._request(texts, self.config.dimensions)

    def detect_dimensions(self) -> int:
        return len(self._request(["知识库连接测试"], None)[0])

    def _request(self, texts: list[str], dimensions: int | None) -> list[list[float]]:
        if not texts or len(texts) > self.config.batch_size:
            raise ValueError("invalid embedding batch size")
        api_key = self.resolve_key()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            with httpx.Client(timeout=self.config.request_timeout, follow_redirects=False) as client:
                for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                    if self.stop is not None:
                        check_stop(self.stop)
                    response = client.post(self.config.embedding_url, headers=headers, json={
                        "model": self.config.embedding_model, "input": texts, "encoding_format": "float",
                    })
                    if response.status_code == 429:
                        logging.getLogger(__name__).warning(
                            "Embedding rate limit: code=%s batch=%s characters=%s attempt=%s",
                            rate_limit_code(response), len(texts), sum(map(len, texts)), attempt + 1,
                        )
                    if response.status_code != 429 or attempt == MAX_RATE_LIMIT_RETRIES:
                        break
                    response.close()
                    logging.getLogger(__name__).warning(
                        "Embedding HTTP 429; retry %s/%s in %s seconds",
                        attempt + 1, MAX_RATE_LIMIT_RETRIES, self.config.retry_interval_seconds,
                    )
                    if self.stop is None:
                        time.sleep(self.config.retry_interval_seconds)
                    elif self.stop.wait(self.config.retry_interval_seconds):
                        raise Interrupted()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"Embedding 连接失败：{type(exc).__name__}，请检查地址与网络") from exc
        if response.status_code != 200:
            # Upstream bodies may echo credentials; expose status, never raw headers/body.
            hints = {
                400: "请检查模型名称、输入限制和接口是否兼容 OpenAI Embeddings",
                401: "API Key 无效或未设置，请重新选择 API Key Name",
                403: "API Key 无权访问该模型或套餐，请检查模型权限和对应的服务地址",
                404: "请核对所填 Base URL、模型名称及服务商的接口说明",
                429: f"已每隔 {self.config.retry_interval_seconds} 秒重试 {MAX_RATE_LIMIT_RETRIES} 次，仍被限流；请检查配额后继续任务",
            }
            raise EmbeddingError(f"Embedding 服务返回 HTTP {response.status_code}；AgentPark 排查提示：" + hints.get(
                response.status_code, "模型服务返回错误，请检查服务状态、模型配置和配额"))
        try:
            payload = response.json()
        except ValueError as exc:
            raise EmbeddingError("Embedding 响应不是 JSON") from exc
        return validate_vectors(payload, len(texts), dimensions)


def validate_vectors(payload, count: int, dimensions: int | None) -> list[list[float]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list) or len(payload["data"]) != count:
        raise EmbeddingError("Embedding 响应 data 数量与输入不一致")
    ordered = {}
    for item in payload["data"]:
        if not isinstance(item, dict) or type(item.get("index")) is not int:
            raise EmbeddingError("Embedding 响应缺少整数 index")
        index, vector = item["index"], item.get("embedding")
        if not 0 <= index < count or index in ordered:
            raise EmbeddingError("Embedding 响应 index 越界或重复")
        if not isinstance(vector, list):
            raise EmbeddingError("Embedding 响应 embedding 必须是数值数组")
        if dimensions is None:
            dimensions = len(vector)
            if not 8 <= dimensions <= 8192:
                raise EmbeddingError(f"模型返回 {dimensions} 维，超出当前支持的 8～8192 维范围")
        if len(vector) != dimensions:
            raise EmbeddingError(f"模型实际返回 {len(vector)} 维，当前索引为 {dimensions} 维；已有向量不能混用，请创建新索引")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector) or not any(vector):
            raise EmbeddingError("Embedding 包含非有限值、非法元素或零向量")
        ordered[index] = [float(v) for v in vector]
    return [ordered[index] for index in range(count)]
