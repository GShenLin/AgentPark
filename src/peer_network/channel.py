from __future__ import annotations

import asyncio
import json
import logging
import struct
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from .contracts import PeerCall, WireRequest, WireResponse


MAX_MESSAGE = 8 * 1024 * 1024
CHUNK_SIZE = 16000
LOGGER = logging.getLogger(__name__)
_REQUEST_TASK: ContextVar[asyncio.Task | None] = ContextVar("peer_request_task", default=None)


class PeerChannel:
    """Bounded ordered RPC; disconnects fail pending calls instead of retrying mutations."""

    def __init__(self, channel, dispatch: Callable[[PeerCall], Awaitable[dict]]):
        self.channel = channel
        self.dispatch = dispatch
        self.pending: dict[str, asyncio.Future] = {}
        self.tasks: set[asyncio.Task] = set()
        self.ready = asyncio.Event()
        self.write_lock = asyncio.Lock()
        self.buffer = bytearray()
        self.expected = 0
        self.closed = False
        channel.on("open", self.ready.set)
        channel.on("close", self.close)
        channel.on("message", self.receive)
        if channel.readyState == "open":
            self.ready.set()

    async def send(self, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(body) > MAX_MESSAGE:
            raise ValueError("Peer response exceeds 8 MiB; request a smaller history window.")
        async with self.write_lock:
            payload = struct.pack("!I", len(body)) + body
            for offset in range(0, len(payload), CHUNK_SIZE):
                async with asyncio.timeout(10):
                    while self.channel.bufferedAmount > 256000:
                        if self.closed:
                            raise ConnectionError("Peer disconnected; delivery may be unknown.")
                        await asyncio.sleep(0.01)
                if self.closed or self.channel.readyState != "open":
                    raise ConnectionError("Peer data channel is not open.")
                self.channel.send(payload[offset:offset + CHUNK_SIZE])

    def receive(self, data) -> None:
        try:
            if not isinstance(data, bytes) or len(data) > CHUNK_SIZE:
                raise ValueError("Invalid peer data frame.")
            self.buffer.extend(data)
            while True:
                if not self.expected:
                    if len(self.buffer) < 4:
                        break
                    self.expected = struct.unpack("!I", self.buffer[:4])[0]
                    del self.buffer[:4]
                    if not 0 < self.expected <= MAX_MESSAGE:
                        raise ValueError("Invalid peer message size.")
                if len(self.buffer) < self.expected:
                    break
                raw = bytes(self.buffer[:self.expected])
                del self.buffer[:self.expected]
                self.expected = 0
                body = json.loads(raw)
                if body.get("kind") == "response":
                    response = WireResponse.model_validate(body)
                    future = self.pending.get(response.request_id)
                    if future is not None and not future.done():
                        future.set_result(response)
                else:
                    request = WireRequest.model_validate(body)
                    if len(self.tasks) >= 8:
                        raise ValueError("Too many concurrent peer requests.")
                    task = asyncio.create_task(self.handle(request))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
        except Exception:
            LOGGER.exception("Closing peer channel after invalid data")
            self.channel.close()
            self.close()

    async def handle(self, request: WireRequest) -> None:
        token = _REQUEST_TASK.set(asyncio.current_task())
        try:
            try:
                result = await self.dispatch(request.call)
                response = WireResponse(request_id=request.request_id, ok=True, result=result)
                # Check the bound before sending so an explicit error can be returned.
                if len(response.model_dump_json().encode("utf-8")) > MAX_MESSAGE:
                    raise ValueError("Response exceeds 8 MiB; request a smaller history window.")
            except Exception as exc:
                detail = getattr(exc, "detail", None)
                response = WireResponse(request_id=request.request_id, ok=False,
                                        error=str(detail if detail is not None else exc)[:2000])
                LOGGER.warning("Peer operation %s failed: %s", request.call.operation, response.error)
            # A settings operation may intentionally close its own transport.
            if not self.closed:
                await self.send(response.model_dump())
        except Exception:
            LOGGER.exception("Unable to return peer response")
            self.channel.close()
            self.close()
        finally:
            _REQUEST_TASK.reset(token)

    async def call(self, call: PeerCall) -> dict:
        if self.closed:
            raise ConnectionError("Peer disconnected.")
        await asyncio.wait_for(self.ready.wait(), 30)
        if len(self.pending) >= 8:
            raise RuntimeError("Too many concurrent outgoing peer requests.")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send(WireRequest(request_id=request_id, call=call).model_dump())
            response = await asyncio.wait_for(future, 45)
            if not response.ok:
                raise RuntimeError(response.error or "Peer rejected the operation.")
            if response.result is None:
                raise ValueError("Peer returned a success response without a result.")
            return response.result
        except TimeoutError as exc:
            raise TimeoutError("Peer response timed out. Delivery is unknown; mutations were not retried.") from exc
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.ready.set()
        self.buffer.clear()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Peer disconnected. Delivery may be unknown; no automatic replay."))
        initiating_request = _REQUEST_TASK.get()
        for task in self.tasks:
            # HTTP middleware may run shutdown in a child task. Preserve the
            # owning RPC request so its cancellation cannot interrupt that child.
            if task is not initiating_request:
                task.cancel()
