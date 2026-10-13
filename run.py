#!/usr/bin/env python
"""统一入口。

    python run.py web                  启动可视化大屏（默认 http://127.0.0.1:8787）
    python run.py cli [--mode mock]    命令行完整演练，打印 Trace 并落盘
    python run.py mcp [--selftest]     以 MCP 服务器运行，供 Agnes Harness 接入
    python run.py agh                  检测 AGH 可用性并生成 AGH 配置
    python run.py selftest             跑冒烟自测

模式说明：
    mock    离线规则规划器（无需 Key/网络）
    builtin 内置 Agent Loop + 真实模型（需 AGNES_API_KEY）
    agh     交由 Agnes Harness 组织任务（需 AGH_HOME 或 agh CLI）
    auto    自动判定（默认）
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from src.config import load_config, resolve_mode  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "outputs")


def cmd_web(args):
    from src.server.app import start_server
    return start_server(args.host, args.port, open_browser=not args.no_browser)


def cmd_cli(args):
    from src.agent.loop import AgentLoop, wait_for_alarm
    from src.tools.lab_tools import build_registry
    from src.report import save_report
    from src.world import LabWorld

    cfg = load_config()
    mode = args.mode or resolve_mode(cfg)
    world = LabWorld(cfg)
    world.start()
    tools = build_registry(world)

    print("=" * 72)
    print("安巡 · 实验室安全应急处置 Agent | 模式: %s | %s" % (mode, world.name))
    print("=" * 72)
    alarm = wait_for_alarm(world)
    print("[监测] %s" % (world.events[-1]["text"] if alarm and world.events else "未检出报警，仍按 SOP 巡检"))
    print("-" * 72)

    def on_step(step):
        print("\n[#%02d][%s] %s (%d ms)" % (step["index"], step["phase"], step["tool"], step["duration_ms"]))
        print("   判断: %s" % step["thought"])
        print("   入参: %s" % json.dumps(step["args"], ensure_ascii=False))
        print("   返回: %s" % json.dumps(step["result"], ensure_ascii=False)[:400])

    loop = AgentLoop(world, tools, cfg, mode=mode, on_step=on_step)
    trace = loop.run(max_steps=args.max_steps)
    world.stop()

    trace_path = trace.save(os.path.join(OUT_DIR, "traces"))
    report_path = None
    if trace.final_report:
        report_path = save_report(trace, world, os.path.join(OUT_DIR, "reports"))

    print("\n" + "=" * 72)
    print("状态: %s | 步数: %d | 耗时: %.1fs" % (trace.status, len(trace.steps), trace.to_dict()["elapsed_sec"]))
    print("轨迹: %s" % trace_path)
    if report_path:
        print("报告: %s" % report_path)
    print("=" * 72)
    return 0 if trace.status == "completed" else 1


def cmd_mcp(args):
    if args.selftest:
        from src.mcp.server import selftest
        return selftest()
    from src.mcp.server import MCPServer
    MCPServer().serve()
    return 0


def cmd_agh(args):
    from src.agh.adapter import AGHBridge
    cfg = load_config()
    bridge = AGHBridge(cfg)
    info = bridge.detect()
    print("AGH 探测结果:")
    print(json.dumps(info, ensure_ascii=False, indent=2))
    path = bridge.write_config(os.path.join(ROOT, "deploy", "agh"))
    print("\n已生成 AGH 配置片段: %s" % path)
    print("MCP 服务器命令: %s" % json.dumps(bridge.mcp_command(), ensure_ascii=False))
    if not info["available"]:
        print("\n当前未检测到 AGH，运行时将自动使用内置 Agent Loop（与 AGH 同构）。")
        print("接入方式见 docs/AGH接入说明.md")
    return 0


def cmd_selftest(args):
    import subprocess
    return subprocess.call([sys.executable, os.path.join(ROOT, "tests", "test_smoke.py")])


def main():
    p = argparse.ArgumentParser(description="安巡 · 实验室安全应急处置 Agent")
    sub = p.add_subparsers(dest="cmd")

    w = sub.add_parser("web", help="启动可视化大屏")
    w.add_argument("--host", default=None)
    w.add_argument("--port", type=int, default=None)
    w.add_argument("--no-browser", action="store_true")
    w.set_defaults(func=cmd_web)

    c = sub.add_parser("cli", help="命令行演练")
    c.add_argument("--mode", choices=["auto", "mock", "builtin", "agh"], default=None)
    c.add_argument("--max-steps", type=int, default=None)
    c.set_defaults(func=cmd_cli)

    m = sub.add_parser("mcp", help="MCP 服务器")
    m.add_argument("--selftest", action="store_true")
    m.set_defaults(func=cmd_mcp)

    a = sub.add_parser("agh", help="AGH 接入探测与配置生成")
    a.set_defaults(func=cmd_agh)

    s = sub.add_parser("selftest", help="冒烟自测")
    s.set_defaults(func=cmd_selftest)

    args = p.parse_args()
    if not args.cmd:
        args = p.parse_args(["web"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
