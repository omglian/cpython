# -*- coding: utf-8 -*-
"""人生重演 (Life Replay) — 文字版 Web 服务器。

零第三方依赖，纯 Python 标准库实现，方便直接部署在任何云主机：

    python3 server.py            # 默认监听 0.0.0.0:8080
    PORT=80 python3 server.py    # 用环境变量换端口

接口：
    GET  /               文字版页面
    POST /api/profile    {"story": "...", "age": 25, "gender": "male"}
                         → 心理侧写 JSON
    POST /api/simulate   {"story": "...", "age": ..., "seed_offset": 0}
                         → 侧写 + 完整人生模拟 JSON
    GET  /api/health     健康检查
"""

import datetime
import json
import os
import sys

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import build_profile, simulate  # noqa: E402
from engine import day as day_engine  # noqa: E402
from engine.events import load_corpus  # noqa: E402

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
MAX_BODY = 512 * 1024  # 单次请求最大 512KB，足够放一篇很长的自传
MAX_STORY = 100_000    # 经历文本最长 10 万字


def _current_year():
    return datetime.date.today().year


class Handler(BaseHTTPRequestHandler):
    server_version = "LifeReplay/0.1"

    # ------------------------------------------------------------------
    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else \
            json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return None
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _extract_inputs(payload):
        story = str(payload.get("story") or "")[:MAX_STORY]
        extra = {}
        try:
            age = int(payload.get("age") or 0)
            if 5 <= age <= 100:
                extra["age"] = age
        except (TypeError, ValueError):
            pass
        if payload.get("gender") in ("male", "female"):
            extra["gender"] = payload["gender"]
        return story, extra

    # ------------------------------------------------------------------
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            path = os.path.join(STATIC_DIR, "index.html")
            try:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, {"error": "页面文件缺失"})
        elif self.path == "/api/health":
            self._send(200, {"ok": True, "service": "life-replay",
                             "event_corpus": len(load_corpus())})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        payload = self._read_json()
        if payload is None:
            self._send(400, {"error": "请求体必须是合法的 JSON 对象"})
            return
        story, extra = self._extract_inputs(payload)
        if len(story.strip()) < 30:
            self._send(400, {"error": "请至少写 30 个字的人生经历——写得越详细，模拟越像你。"})
            return

        if self.path == "/api/day":
            # 逐日模拟：状态在前后端之间来回传，服务端保持无状态。
            # 没有 state 就是开新的一轮，有 state 就往下生成一天。
            profile = build_profile(story, extra, current_year=_current_year())
            state = payload.get("state")
            if not isinstance(state, dict) or "day_index" not in state:
                state = day_engine.start(profile, start_year=_current_year())
            try:
                day, state = day_engine.next_day(profile, state, seed_text=story)
            except (KeyError, TypeError, ValueError):
                self._send(400, {"error": "模拟状态无效，请重新开始。"})
                return
            self._send(200, {"day": day, "state": state, "profile": profile})
            return

        if self.path == "/api/profile":
            profile = build_profile(story, extra, current_year=_current_year())
            self._send(200, {"profile": profile})
        elif self.path == "/api/simulate":
            profile = build_profile(story, extra, current_year=_current_year())
            try:
                seed_offset = int(payload.get("seed_offset") or 0)
            except (TypeError, ValueError):
                seed_offset = 0
            result = simulate(
                profile,
                seed_text=story,
                seed_offset=seed_offset,
                start_year=_current_year(),
            )
            self._send(200, {"profile": profile, "simulation": result})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.address_string(), fmt % args))


def main():
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("人生重演 · 文字版 已启动: http://%s:%d/" % (host, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
