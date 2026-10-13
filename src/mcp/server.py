"""MCP（Model Context Protocol）服务器：把实验室设备暴露给 Agnes Harness。

以 stdio + JSON-RPC 2.0 实现，零第三方依赖。AGH 通过配置拉起本进程，
即可在 Agent Loop 中调用全部设备工具；也可单独自测：
    python run.py mcp --selftest
"""

import json
import sys

from src.config import load_config
from src.tools.lab_tools import build_registry
from src.world import LabWorld

PROTOCOL_VERSION = "2024-11-05"


class MCPServer:
    def __init__(self):
        self.cfg = load_config()
        self.world = LabWorld(self.cfg)
        self.world.start()
        self.tools = build_registry(self.world)

    # ---------- 协议处理 ----------
    def handle(self, request):
        method = request.get("method")
        rid = request.get("id")

        if method == "initialize":
            return self._reply(rid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "labguard-devices", "version": "1.0.0"},
            })

        if method == "tools/list":
            return self._reply(rid, {"tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.parameters,
                }
                for t in [self.tools.get(n) for n in self.tools.names()]
            ]})

        if method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})
            outcome = self.tools.call(name, args)
            return self._reply(rid, {
                "content": [{"type": "text", "text": json.dumps(outcome["result"], ensure_ascii=False)}],
                "isError": not outcome["ok"],
            })

        if method == "ping":
            return self._reply(rid, {})

        return self._reply(rid, None, error={"code": -32601, "message": "不支持的方法: %s" % method})

    def _reply(self, rid, result, error=None):
        resp = {"jsonrpc": "2.0", "id": rid}
        if error:
            resp["error"] = error
        else:
            resp["result"] = result
        return resp

    # ---------- 主循环 ----------
    def serve(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            resp = self.handle(req)
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()


def selftest():
    """冒烟自测：不依赖 AGH，直接验证 MCP 协议响应符合预期。"""
    server = MCPServer()
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    listing = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    call = server.handle({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_sensor_readings", "arguments": {}},
    })
    ok = (
        init["result"]["serverInfo"]["name"] == "labguard-devices"
        and len(listing["result"]["tools"]) >= 14
        and "readings" in json.loads(call["result"]["content"][0]["text"])
    )
    print("MCP initialize ->", init["result"]["serverInfo"])
    print("MCP tools/list -> %d 个工具" % len(listing["result"]["tools"]))
    print("MCP tools/call ->", json.loads(call["result"]["content"][0]["text"])["readings"])
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1
