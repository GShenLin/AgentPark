def test_resolve_local_path_handles_windows_file_uri():
    from src.channels.weixin.media import resolve_local_path

    resolved = resolve_local_path("file:///C:/tmp/weixin%20image.png")

    assert resolved.replace("\\", "/").endswith("C:/tmp/weixin image.png")


def test_driver_converts_inbound_image_to_resource_part(monkeypatch, tmp_path):
    from src.channels.weixin import driver as driver_module

    image_path = tmp_path / "inbound.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\npayload")

    def fake_download(image_item, *, cdn_base_url, label):
        assert image_item == {"media": {"encrypt_query_param": "download-param"}}
        assert cdn_base_url == "https://cdn.example.com/c2c"
        assert label == "inbound image"
        return str(image_path), "image/png"

    monkeypatch.setattr(driver_module, "download_and_decrypt_image", fake_download)
    monkeypatch.setattr(
        driver_module.WeixinChannelDriver,
        "_load_account",
        lambda self, account_id: {
            "accountId": account_id,
            "token": "token",
            "baseUrl": "https://api.example.com",
            "cdnBaseUrl": "https://cdn.example.com/c2c",
        },
    )

    envelope = driver_module.WeixinChannelDriver().message_to_envelope(
        account_id="acct-1",
        message={
            "from_user_id": "user-1@im.wechat",
            "to_user_id": "bot-1",
            "message_id": "msg-1",
            "item_list": [
                {
                    "type": 2,
                    "image_item": {"media": {"encrypt_query_param": "download-param"}},
                }
            ],
        },
    )

    resources = [
        part.get("resource") or {}
        for part in envelope.get("parts") or []
        if isinstance(part, dict) and part.get("type") == "resource"
    ]
    assert len(resources) == 1
    assert resources[0]["kind"] == "image"
    assert resources[0]["uri"] == str(image_path)
    assert resources[0]["mime"] == "image/png"
    assert "metadata" not in resources[0]
    assert "source" not in resources[0]
    assert not [part for part in envelope.get("parts") or [] if isinstance(part, dict) and part.get("type") == "meta"]


def test_driver_attaches_recent_image_context_to_followup_text(monkeypatch, tmp_path):
    from src.channels.weixin import driver as driver_module
    from src.channels.weixin import storage

    account_id = "acct-context"
    user_id = "user-context@im.wechat"
    image_path = tmp_path / "inbound.jpg"
    image_path.write_bytes(b"\xff\xd8\xffpayload")

    monkeypatch.setattr(storage, "accounts_dir", lambda: str(tmp_path / "accounts"))
    monkeypatch.setattr(
        driver_module.WeixinChannelDriver,
        "_load_account",
        lambda self, account_id: {
            "accountId": account_id,
            "token": "token",
            "baseUrl": "https://api.example.com",
            "cdnBaseUrl": "https://cdn.example.com/c2c",
        },
    )
    monkeypatch.setattr(
        driver_module,
        "download_and_decrypt_image",
        lambda image_item, *, cdn_base_url, label: (str(image_path), "image/jpeg"),
    )

    driver = driver_module.WeixinChannelDriver()
    driver.message_to_envelope(
        account_id=account_id,
        message={
            "from_user_id": user_id,
            "to_user_id": "bot-1",
            "message_id": "img-1",
            "item_list": [{"type": 2, "image_item": {"media": {"encrypt_query_param": "download-param"}}}],
        },
    )
    followup = driver.message_to_envelope(
        account_id=account_id,
        message={
            "from_user_id": user_id,
            "to_user_id": "bot-1",
            "message_id": "txt-1",
            "item_list": [{"type": 1, "text_item": {"text": "这图里是个啥？"}}],
        },
    )

    assert any(part.get("type") == "text" and part.get("text") == "这图里是个啥？" for part in followup["parts"])
    resources = [
        part.get("resource") or {}
        for part in followup.get("parts") or []
        if isinstance(part, dict) and part.get("type") == "resource"
    ]
    assert len(resources) == 1
    assert resources[0]["kind"] == "image"
    assert resources[0]["uri"] == str(image_path)
    assert resources[0]["mime"] == "image/jpeg"
    assert resources[0]["metadata"]["context"] == "recent_channel_image"


def test_driver_batches_multiple_image_messages_until_followup_text(monkeypatch, tmp_path):
    from src.channels.weixin import driver as driver_module
    from src.channels.weixin import storage

    account_id = "acct-batch"
    user_id = "user-batch@im.wechat"
    image_paths = [tmp_path / "first.jpg", tmp_path / "second.jpg", tmp_path / "third.jpg"]
    for image_path in image_paths:
        image_path.write_bytes(b"\xff\xd8\xffpayload")
    download_index = {"value": 0}

    monkeypatch.setattr(storage, "accounts_dir", lambda: str(tmp_path / "accounts"))
    monkeypatch.setattr(
        driver_module.WeixinChannelDriver,
        "_load_account",
        lambda self, account_id: {
            "accountId": account_id,
            "token": "token",
            "baseUrl": "https://api.example.com",
            "cdnBaseUrl": "https://cdn.example.com/c2c",
        },
    )

    def fake_download(image_item, *, cdn_base_url, label):
        path = image_paths[download_index["value"]]
        download_index["value"] += 1
        return str(path), "image/jpeg"

    monkeypatch.setattr(driver_module, "download_and_decrypt_image", fake_download)

    driver = driver_module.WeixinChannelDriver()
    for index in range(3):
        driver.message_to_envelope(
            account_id=account_id,
            message={
                "from_user_id": user_id,
                "to_user_id": "bot-1",
                "message_id": f"img-{index}",
                "item_list": [{"type": 2, "image_item": {"media": {"encrypt_query_param": f"param-{index}"}}}],
            },
        )

    followup = driver.message_to_envelope(
        account_id=account_id,
        message={
            "from_user_id": user_id,
            "to_user_id": "bot-1",
            "message_id": "txt-1",
            "item_list": [{"type": 1, "text_item": {"text": "这几张分别是啥？"}}],
        },
    )

    resources = [
        part.get("resource") or {}
        for part in followup.get("parts") or []
        if isinstance(part, dict) and part.get("type") == "resource"
    ]
    assert [item.get("uri") for item in resources] == [str(path) for path in image_paths]
    assert all((item.get("metadata") or {}).get("context") == "recent_channel_image" for item in resources)

    next_text = driver.message_to_envelope(
        account_id=account_id,
        message={
            "from_user_id": user_id,
            "to_user_id": "bot-1",
            "message_id": "txt-2",
            "item_list": [{"type": 1, "text_item": {"text": "下一句不该继续带图"}}],
        },
    )
    assert not [
        part for part in next_text.get("parts") or [] if isinstance(part, dict) and part.get("type") == "resource"
    ]


def test_driver_saves_inbound_message_as_default_channel_target(monkeypatch, tmp_path):
    from src.channels.weixin import driver as driver_module
    from src.channels.weixin import storage

    monkeypatch.setattr(storage, "state_root", lambda: str(tmp_path / "channel_state"))

    envelope = driver_module.WeixinChannelDriver().message_to_envelope(
        account_id="acct-1",
        message={
            "from_user_id": "user-1@im.wechat",
            "to_user_id": "bot-1",
            "context_token": "ctx-1",
            "message_id": "msg-1",
            "item_list": [{"type": 1, "text_item": {"text": "hello"}}],
        },
    )

    assert storage.load_default_target() == {
        "channel": "openclaw-weixin",
        "accountId": "acct-1",
        "toUserId": "user-1@im.wechat",
        "contextToken": "ctx-1",
    }
    assert not [part for part in envelope.get("parts") or [] if isinstance(part, dict) and part.get("type") == "meta"]


def test_agent_builds_multimodal_content_from_recent_channel_image(tmp_path):
    from nodes.agent_message_adapter import build_agent_user_content

    image_path = tmp_path / "inbound.jpg"
    image_path.write_bytes(b"\xff\xd8\xffpayload")

    content = build_agent_user_content(
        "openai-test-provider",
        "chat",
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "这图里是个啥？"},
                {
                    "type": "resource",
                    "resource": {
                        "kind": "image",
                        "uri": str(image_path),
                        "mime": "image/jpeg",
                        "metadata": {"context": "recent_channel_image"},
                    },
                },
            ],
        },
    )

    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "这图里是个啥？"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_channel_service_status_update_preserves_runner_queue_state(tmp_path):
    from src.channels.service import ChannelService
    from src.web_backend import state_store

    config_path = tmp_path / "ChannelReceiver" / "config.json"
    state_store._write_json_dict(
        str(config_path),
        {
            "node_id": "ChannelReceiver",
            "type_id": "channel_receiver_node",
            "state": "working",
            "pending": [],
            "pending_count": 0,
            "inflight": {"trace_id": "trace-1", "payload": "message-1"},
            "last_message": "",
        },
    )

    class FakeGraphRuntime:
        def _node_config_path(self, node_id, graph_id):
            assert node_id == "ChannelReceiver"
            assert graph_id == "default"
            return str(config_path)

    class FakeCore:
        graph_runtime = FakeGraphRuntime()

    ChannelService(FakeCore())._set_receiver_state("default", "ChannelReceiver", "idle", "receiver saw message")

    cfg = state_store._read_json_dict(str(config_path))
    assert cfg["state"] == "working"
    assert cfg["pending"] == []
    assert cfg["pending_count"] == 0
    assert cfg["inflight"] == {"trace_id": "trace-1", "payload": "message-1"}
    assert cfg["last_message"] == "receiver saw message"


