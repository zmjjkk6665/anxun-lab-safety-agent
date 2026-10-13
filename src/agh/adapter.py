"""Agnes Harness 适配层。

设计原则：核心任务的组织与工具调用始终由 Harness 承担。
  1. 检测到 AGH 可用（AGH_HOME 存在 / agh CLI 在 PATH / 配置了 App Server）
     → 通过 MCP 把实验室设备工具注册给 AGH，由 AGH 的 Agent Loop 驱动任务；
  2. 当前环境无 AGH 源码时 → 使用与 AGH 同构的内置 Agent Loop 执行同一份工具注册表，
     保证演练、测试、演示不中断，替换为 AGH 时无需改动任何工具代码。

接入 AGH 只需两步（详见 docs/AGH接入说明.md）：
  1. 把仓库中 deploy/agh/ 下的配置合并进 AGH 配置，声明 MCP 服务器；
  2. 设置环境变量 AGH_HOME 指向 AGH 源码目录，运行时自动切换为 AGH 模式。
"""

import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AGHBridge:
    def __init__(self, cfg):
        self.cfg = cfg
        self.agh_cfg = cfg.get("agh", {})
        self.home = self.agh_cfg.get("home") or os.environ.get("AGH_HOME", "")
        self.cli = self.agh_cfg.get("cli", "agh")
        self.server_url = self.agh_cfg.get("server_url") or os.environ.get("AGH_SERVER_URL", "")

    def detect(self):
        """探测本机 AGH 可用性，返回可用于排障的明细。"""
        cli_path = shutil.which(self.cli)
        home_exists = bool(self.home) and os.path.isdir(self.home)
        return {
            "agh_home": self.home or None,
            "agh_home_exists": home_exists,
            "cli": self.cli,
            "cli_path": cli_path,
            "server_url": self.server_url or None,
            "available": bool(home_exists or cli_path or self.server_url),
        }

    def mcp_command(self):
        """AGH 拉起本项目 MCP 服务器的命令。"""
        return {
            "name": "labguard-devices",
            "command": "python",
            "args": [os.path.join(ROOT, "run.py"), "mcp"],
            "transport": "stdio",
        }

    def write_config(self, out_dir):
        """生成可直接被 AGH 加载的配置片段。"""
        os.makedirs(out_dir, exist_ok=True)
        cfg = {
            "model": {
                "provider": self.cfg["llm"].get("provider", "agnes"),
                "base_url": self.cfg["llm"]["base_url"],
                "model": self.cfg["llm"]["model"],
                "api_key_env": "AGNES_API_KEY",
            },
            "mcpServers": [self.mcp_command()],
            "skills": [os.path.join(ROOT, "skills", "chemical-leak-response")],
        }
        path = os.path.join(out_dir, "agh.labguard.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return path

    def run_task(self, instruction, workdir=None, timeout_sec=600):
        """调用 AGH CLI 执行任务（AGH 模式下的核心入口）。"""
        info = self.detect()
        if not info["cli_path"] and not info["agh_home_exists"]:
            raise RuntimeError(
                "未检测到 Agnes Harness。请设置 AGH_HOME 指向 AGH 源码目录，"
                "或将 agh 加入 PATH。当前探测结果: %s" % json.dumps(info, ensure_ascii=False)
            )
        cmd = [info["cli_path"] or self.cli, "--workdir", workdir or ROOT, "--task", instruction]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, encoding="utf-8")
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
