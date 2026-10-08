"""Room/user-scoped Volcengine RTC v001 tokens; AppKey never leaves the server."""
import base64
import hashlib
import hmac
import secrets
import struct
import time


def rtc_token(app_id: str, app_key: str, room: str, user: str, *,
              issued: int | None = None, nonce: int | None = None) -> str:
    if len(app_id) != 24 or not app_key or not room or not user:
        raise ValueError("RTC Token requires AppId, AppKey, room and user.")
    now = int(time.time()) if issued is None else issued
    expiry = now + 3600

    def blob(value: bytes) -> bytes:
        return struct.pack("<H", len(value)) + value

    message = (struct.pack("<III", secrets.randbits(32) if nonce is None else nonce, now, expiry)
               + blob(room.encode("utf-8")) + blob(user.encode("utf-8"))
               + struct.pack("<H", 5)
               + b"".join(struct.pack("<HI", privilege, expiry) for privilege in range(5)))
    signature = hmac.new(app_key.encode("utf-8"), message, hashlib.sha256).digest()
    return "001" + app_id + base64.b64encode(blob(message) + blob(signature)).decode("ascii")
