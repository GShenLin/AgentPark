from pathlib import Path


def test_channel_sender_sends_image_resource_with_config(monkeypatch, tmp_path):
    from nodes import channel_sender_node

    image_path = tmp_path / "reply.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npayload")
    calls = []

    class FakeDriver:
        def send_text(self, **kwargs):
            calls.append(("text", kwargs))
            return {"message_id": "text-1"}

        def send_image(self, **kwargs):
            calls.append(("image", kwargs))
            return {"message_id": "image-1"}

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    result = channel_sender_node.Node().on_input(
        {
            "role": "assistant",
            "parts": [
                {
                    "type": "resource",
                    "resource": {"kind": "image", "uri": str(image_path), "mime": "image/png"},
                }
            ],
        },
        {
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "ToUserId": "user-1@im.wechat",
            "ContextToken": "ctx-1",
        },
    )

    assert calls == [
        (
            "image",
            {
                "account_id": "acct-1",
                "to_user_id": "user-1@im.wechat",
                "file_path": str(image_path),
                "context_token": "ctx-1",
                "timeout_seconds": 15,
            },
        )
    ]
    payload = result["routes"][0]["payload"]
    assert payload["data"]["image_count"] == 1
    assert payload["data"]["message_ids"] == ["image-1"]


def test_channel_sender_sends_configured_text_without_inbound_meta(monkeypatch):
    from nodes import channel_sender_node

    calls = []

    class FakeDriver:
        def send_text(self, **kwargs):
            calls.append(kwargs)
            return {"message_id": "text-1"}

        def send_image(self, **kwargs):
            raise AssertionError("send_image should not run")

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    result = channel_sender_node.Node().on_input(
        "hello from configured sender",
        {
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "ToUserId": "user-1@im.wechat",
        },
    )

    assert calls == [
        {
            "account_id": "acct-1",
            "to_user_id": "user-1@im.wechat",
            "text": "hello from configured sender",
            "context_token": "",
            "timeout_seconds": 15,
        }
    ]
    payload = result["routes"][0]["payload"]
    assert payload["data"]["message_ids"] == ["text-1"]


def test_channel_sender_prepends_configured_name_to_text(monkeypatch):
    from nodes import channel_sender_node

    calls = []

    class FakeDriver:
        def send_text(self, **kwargs):
            calls.append(kwargs)
            return {"message_id": "text-1"}

        def send_image(self, **kwargs):
            raise AssertionError("send_image should not run")

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    channel_sender_node.Node().on_input(
        "answer body",
        {
            "Channel": "openclaw-weixin",
            "Name": "ChatGPT",
            "AccountId": "acct-1",
            "ToUserId": "user-1@im.wechat",
        },
    )

    assert calls[0]["text"] == "ChatGPT:\nanswer body"


def test_channel_sender_rejects_invalid_timeout(monkeypatch):
    from nodes import channel_sender_node
    from src.channels.errors import ChannelConfigError

    class FakeDriver:
        def send_text(self, **_kwargs):
            raise AssertionError("send_text should not run")

        def send_image(self, **_kwargs):
            raise AssertionError("send_image should not run")

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    try:
        channel_sender_node.Node().on_input(
            "answer body",
            {
                "Channel": "openclaw-weixin",
                "AccountId": "acct-1",
                "ToUserId": "user-1@im.wechat",
                "TimeoutSeconds": "soon",
            },
        )
    except ChannelConfigError as exc:
        assert "TimeoutSeconds must be an integer" in str(exc)
    else:
        raise AssertionError("ChannelSender should reject invalid TimeoutSeconds")


def test_channel_sender_uses_default_channel_target(monkeypatch, tmp_path):
    from nodes import channel_sender_node
    from src.channels.weixin import storage

    monkeypatch.setattr(storage, "state_root", lambda: str(tmp_path / "channel_state"))
    storage.save_default_target("acct-1", "user-1@im.wechat", "ctx-default")
    calls = []

    class FakeDriver:
        def send_text(self, **kwargs):
            calls.append(kwargs)
            return {"message_id": "text-1"}

        def send_image(self, **kwargs):
            raise AssertionError("send_image should not run")

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    channel_sender_node.Node().on_input(
        "hello from default channel target",
        {"Channel": "openclaw-weixin"},
    )

    assert calls == [
        {
            "account_id": "acct-1",
            "to_user_id": "user-1@im.wechat",
            "text": "hello from default channel target",
            "context_token": "ctx-default",
            "timeout_seconds": 15,
        }
    ]


def test_channel_sender_loads_context_token_from_channel_state(monkeypatch, tmp_path):
    from nodes import channel_sender_node
    from src.channels.weixin import storage

    monkeypatch.setattr(storage, "accounts_dir", lambda: str(tmp_path / "accounts"))
    storage.save_context_token("acct-1", "user-1@im.wechat", "ctx-from-state")
    calls = []

    class FakeDriver:
        def send_text(self, **kwargs):
            calls.append(kwargs)
            return {"message_id": "text-1"}

        def send_image(self, **kwargs):
            raise AssertionError("send_image should not run")

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    channel_sender_node.Node().on_input(
        "state token reply",
        {
            "Channel": "openclaw-weixin",
            "AccountId": "acct-1",
            "ToUserId": "user-1@im.wechat",
        },
    )

    assert calls[0]["context_token"] == "ctx-from-state"


def test_channel_sender_does_not_use_meta_as_recipient_config(monkeypatch):
    from nodes import channel_sender_node
    from src.channels.errors import ChannelConfigError
    from src.channels.weixin import storage

    monkeypatch.setattr(storage, "load_default_target", lambda: {})

    class FakeDriver:
        def send_text(self, **kwargs):
            raise AssertionError("send_text should not run")

        def send_image(self, **kwargs):
            raise AssertionError("send_image should not run")

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    try:
        channel_sender_node.Node().on_input(
            {
                "parts": [
                    {"type": "text", "text": "implicit recipient should fail"},
                    {
                        "type": "meta",
                        "meta": {
                            "channel": "openclaw-weixin",
                            "accountId": "acct-1",
                            "from": "user-1@im.wechat",
                            "contextToken": "ctx-1",
                        },
                    },
                ],
            },
            {"Channel": "openclaw-weixin"},
        )
    except ChannelConfigError as exc:
        assert str(exc) == "ChannelSender requires a logged-in or recently active Weixin account"
    else:
        raise AssertionError("ChannelSender should require explicit recipient config")


def test_channel_sender_keeps_text_and_image_as_separate_sends(monkeypatch, tmp_path):
    from nodes import channel_sender_node

    image_path = Path(tmp_path) / "reply.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npayload")
    calls = []

    class FakeDriver:
        def send_text(self, **kwargs):
            calls.append(("text", kwargs["text"]))
            return {"message_id": "text-1"}

        def send_image(self, **kwargs):
            calls.append(("image", kwargs["file_path"]))
            return {"message_id": "image-1"}

    monkeypatch.setattr(channel_sender_node, "WeixinChannelDriver", FakeDriver)

    channel_sender_node.Node().on_input(
        {
            "parts": [
                {"type": "text", "text": "caption"},
                {"type": "resource", "resource": {"kind": "image", "uri": str(image_path)}},
            ],
        },
        {
            "AccountId": "acct-1",
            "ToUserId": "user-1@im.wechat",
            "ContextToken": "ctx-1",
        },
    )

    assert calls == [("text", "caption"), ("image", str(image_path))]
