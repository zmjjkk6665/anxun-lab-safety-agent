"""可视化服务：stdlib HTTP 服务，零第三方依赖，离线可跑。

GET  /                 前端大屏
GET  /api/state        实验室实时状态
GET  /api/trace        Agent 执行轨迹
GET  /api/tools        工具注册表
GET  /api/agh          AGH 可用性探测结果
POST /api/run          启动一次应急处置（body: {"mode": "auto|mock|builtin"}）
POST /api/reset        重置演练场景
"""

import json
import os
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.agh.adapter import AGHBridge
from src.agent.loop import AgentLoop, wait_for_alarm
from src.config import load_config, resolve_mode
from src.tools.lab_tools import build_registry
from src.world import LabWorld

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEB_DIR = os.path.join(ROOT, "src", "web")


class Session:
    """一次演练会话：世界 + 工具 + Agent Loop + 轨迹。"""

    def __init__(self, cfg):
        self.cfg = cfg
        # 必须为可重入锁：run() 持锁后会调用 reset()
        self.lock = threading.RLock()
        self.world = LabWorld(cfg)
        self.world.start()
        self.tools = build_registry(self.world)
        self.trace = None
        self.status = "idle"
        self.mode = None
        self.thread = None

    def reset(self):
        with self.lock:
            self._reset_locked()

    def _reset_locked(self):
        self.world.stop()
        self.world = LabWorld(self.cfg)
        self.world.start()
        self.tools = build_registry(self.world)
        self.trace = None
        self.status = "idle"

    def run(self, mode=None):
        with self.lock:
            if self.status == "running":
                return {"started": False, "reason": "已有任务在执行"}
            self._reset_locked()
            mode = mode or resolve_mode(self.cfg)
            self.mode = mode
            self.status = "running"

        def job():
            wait_for_alarm(self.world)
            loop = AgentLoop(self.world, self.tools, self.cfg, mode=mode)
            loop.run()
            with self.lock:
                self.trace = loop.trace
                self.status = "completed" if loop.trace.status == "completed" else loop.trace.status

        t = threading.Thread(target=job, daemon=True)
        self.thread = t
        t.start()
        return {"started": True, "mode": mode}

    def state(self):
        snap = self.world.snapshot()
        snap["run"] = {
            "status": self.status,
            "mode": self.mode,
            "trace": self.trace.to_dict() if self.trace else None,
        }
        return snap


class Handler(BaseHTTPRequestHandler):
    session: Session = None
    cfg: dict = {}

    def log_message(self, fmt, *args):
        pass

    # ---------- 路由 ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
        if path in ("/app.js", "/style.css"):
            return self._file(os.path.join(WEB_DIR, path.lstrip("/")),
                              "application/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8")
        if path == "/api/state":
            return self._json(self.session.state())
        if path == "/api/trace":
            return self._json(self.session.trace.to_dict() if self.session.trace else {"steps": []})
        if path == "/api/tools":
            return self._json(self.session.tools.schemas())
        if path == "/api/agh":
            return self._json(AGHBridge(self.cfg).detect())
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        if path == "/api/run":
            return self._json(self.session.run(body.get("mode")))
        if path == "/api/reset":
            self.session.reset()
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)

    # ---------- 响应工具 ----------
    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._json({"error": "文件缺失: %s" % path}, 404)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def start_server(host=None, port=None, open_browser=False):
    cfg = load_config()
    Handler.cfg = cfg
    Handler.session = Session(cfg)
    host = host or cfg["server"]["host"]
    port = port or cfg["server"]["port"]
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = "http://%s:%d/" % (host, port)
    print("安巡 · 实验室安全应急处置 Agent 已启动：%s" % url)
    if open_browser:
        threading.Timer(1.0, lambda: __import__("webbrowser").open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        Handler.session.world.stop()
    return 0
