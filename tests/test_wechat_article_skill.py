import io
import json
from pathlib import Path
import runpy

import pytest

from nodes.agent_skill_loader import load_node_skills
from nodes.agent_skill_scripts import register_skill_script_tools
from src.providers.curl_types import CurlResponse, CurlTransportError
from src.tool.base_tool import BaseTool
from src.wechat_articles.embedded import ArticleParseError, string_literal
from src.wechat_articles.parser import parse_article
from src.wechat_articles.reader import read_article, validate_url


ROOT = Path(__file__).resolve().parents[1]
URL = "https://mp.weixin.qq.com/s/example"
IMAGE = "https://mmbiz.qpic.cn/image/0?wx_fmt=png&from=appmsg"
ARTICLE = f'''<h1 id="activity-name">中文 &amp; 标题</h1>
<a id="js_name">公众号</a><span id="js_author_name">作者</span>
<span id="publish_time">2026-09-19 10:00</span><nav>不要收录导航</nav>
<div id="js_content"><h2>小节</h2><p>正文😀</p>
<img src="placeholder" data-src="{IMAGE}">
<a href="/s/next">下一篇</a><a href="javascript:alert(1)">危险链接</a>
<table><tr><th>项目</th><th>数量</th></tr><tr><td>测试</td><td>2</td></tr></table>
<script>doNotExecute()</script></div>'''
POST = r'''<script>window.cgiDataNew = {
  nested: {title: '不是标题', cdn_url: '不是配图'},
  title: '图文😀', nick_name: '账号', author: '', create_time: '2026-09-19 10:00',
  desc: '截断的摘要', content_noencode: '完整正文\x0a第二行\u4e2d\u6587\ud83d\ude00',
  picture_page_info_list: [
    {cdn_url: 'https://mmbiz.qpic.cn/image/0?wx_fmt=png\x26amp;from=appmsg',
     width: '896' * 1, nested: {title: '忽略 } 和 , 以及 \' 引号'}},
    {cdn_url: 'https://mmbiz.qpic.cn/second/0?wx_fmt=jpeg'}
  ], type: '9' * 1
};</script>'''


def test_standard_article_keeps_structure_and_lazy_images():
    article = parse_article(ARTICLE, URL)
    assert article.title == "中文 & 标题"
    assert article.account == "公众号" and article.author == "作者"
    assert article.published_at == "2026-09-19 10:00"
    assert "## 小节" in article.markdown and "正文😀" in article.markdown
    assert "| 项目 | 数量 |" in article.markdown
    assert "/s/next" in article.markdown and "javascript:" not in article.markdown
    assert "不要收录导航" not in article.markdown and "doNotExecute" not in article.markdown
    assert article.images == [IMAGE] and article.warnings


def test_picture_post_uses_complete_text_and_ordered_images():
    article = parse_article(POST, URL)
    assert article.format == "picture_post"
    assert article.title == "图文😀" and article.author is None
    assert article.markdown.startswith("完整正文\n第二行中文😀")
    assert "截断的摘要" not in article.markdown and "不是标题" not in article.markdown
    assert article.images == [IMAGE, "https://mmbiz.qpic.cn/second/0?wx_fmt=jpeg"]
    assert article.markdown.index("配图 1") < article.markdown.index("配图 2")


@pytest.mark.parametrize("page", [
    "<h1>环境异常</h1><p>请完成验证</p>", "<h1>该内容已被发布者删除</h1>",
    '<h1 id="activity-name">空</h1><div id="js_content"></div>',
    POST.replace("content_noencode:", "unknown_content:"),
    POST.replace("title: '图文😀'", "title: executeCode()"),
])
def test_unreadable_or_unknown_page_never_becomes_article(page):
    with pytest.raises(ArticleParseError):
        parse_article(page, URL)


def test_string_reader_does_not_evaluate_code():
    assert string_literal(r"'中文\x0a\u4e2d\ud83d\ude00'") == "中文\n中😀"
    for raw in ("'title' + run()", r"'broken\xGG'", "'unterminated", r"'\ud800'"):
        with pytest.raises(ArticleParseError):
            string_literal(raw)


@pytest.mark.parametrize("url", [
    "http://mp.weixin.qq.com/s/test", "https://mp.weixin.qq.com.evil.test/s/test",
    "https://127.0.0.1/s/test", "https://mp.weixin.qq.com:444/s/test",
    "https://name@mp.weixin.qq.com/s/test", "https://mp.weixin.qq.com/other",
    "https://mp.weixin.qq.com/s/test\n", 1,
])
def test_url_boundary(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_curl_redirect_rechecked_and_utf8_preserved(monkeypatch):
    calls = []
    responses = iter([
        CurlResponse("", 302, {"location": "/s/next"}),
        CurlResponse("", 200, {"content-type": "text/html; charset=UTF-8"}, ARTICLE.encode()),
    ])

    def request(self, **kwargs):
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr("src.wechat_articles.reader.CurlHttpTransport.request", request)
    result = read_article(URL)
    assert result.title == "中文 & 标题" and result.source_url.endswith("/s/next")
    assert len(calls) == 2 and all(c["follow_redirects"] is False for c in calls)
    assert calls[1]["timeout_sec"] <= calls[0]["timeout_sec"]


def test_unsafe_redirect_stops_before_second_request(monkeypatch):
    calls = []

    def request(self, **kwargs):
        calls.append(kwargs)
        return CurlResponse("", 302, {"location": "https://127.0.0.1/private"})

    monkeypatch.setattr("src.wechat_articles.reader.CurlHttpTransport.request", request)
    with pytest.raises(ValueError):
        read_article(URL)
    assert len(calls) == 1


@pytest.mark.parametrize("response", [
    CurlResponse("<p>forbidden</p>", 403, {"content-type": "text/html"}),
    CurlResponse("{}", 200, {"content-type": "application/json"}),
    CurlResponse("<p>请验证</p>", 200, {"content-type": "text/html"}),
])
def test_http_errors_and_challenges_are_failures(monkeypatch, response):
    monkeypatch.setattr("src.wechat_articles.reader.CurlHttpTransport.request", lambda *a, **kw: response)
    with pytest.raises(ArticleParseError):
        read_article(URL)


def test_transport_failure_is_not_hidden(monkeypatch):
    def request(*args, **kwargs):
        raise CurlTransportError("network failed")

    monkeypatch.setattr("src.wechat_articles.reader.CurlHttpTransport.request", request)
    with pytest.raises(CurlTransportError, match="network failed"):
        read_article(URL)


def test_real_skill_registers_and_script_runs_from_its_own_directory(monkeypatch):
    class Agent:
        config = {}

    agent = Agent()
    agent.tools = BaseTool(agent)
    skills = load_node_skills(["wechat-article"], node_id="test", skill_root=str(ROOT / ".agents/skills"))
    assert register_skill_script_tools(agent, skills) == ["skill__wechat-article__read"]
    # A rejected URL tests the real subprocess import path without network dependence.
    result = json.loads(agent.tools.function_map["skill__wechat-article__read"](url="https://example.com"))
    assert result["status"] == "error" and result["exit_code"] == 1
    assert json.loads(result["stderr"])["type"] == "ValueError"
    assert not result["stdout"]


def test_script_serializes_chinese_losslessly(monkeypatch, capsys):
    namespace = runpy.run_path(str(ROOT / ".agents/skills/wechat-article/scripts/read.py"))
    namespace["main"].__globals__["read_article"] = lambda url: parse_article(POST, url)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"url": URL})))
    namespace["main"]()
    output = capsys.readouterr().out
    assert output.isascii() and json.loads(output)["title"] == "图文😀"
