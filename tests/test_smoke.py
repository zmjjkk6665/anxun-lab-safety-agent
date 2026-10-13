"""冒烟测试：对 CLI / MCP / HTTP 三条运行通道做真实端到端验证。

运行：python tests/test_smoke.py
"""

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.config import load_config  # noqa: E402
from src.tools.lab_tools import build_registry  # noqa: E402
from src.world import LabWorld  # noqa: E402


class TestWorldAndTools(unittest.TestCase):
    def test_devices_registered(self):
        world = LabWorld(load_config())
        registry = build_registry(world)
        self.assertGreaterEqual(len(registry.names()), 14)
        for name in ["get_sensor_readings", "close_gas_valve", "arm_manual_shutoff", "submit_report"]:
            self.assertIn(name, registry.names())

    def test_remote_valve_fault_then_manual_shutoff(self):
        world = LabWorld(load_config())
        registry = build_registry(world)
        self.assertFalse(registry.call("close_gas_valve", {"valve_id": "VALVE-01"})["ok"])
        out = registry.call("arm_manual_shutoff", {"arm_id": "ARM-01", "valve_id": "VALVE-01"})
        self.assertTrue(out["ok"])
        self.assertFalse(world.valve.state["open"])

    def test_unknown_tool_reports_error(self):
        world = LabWorld(load_config())
        registry = build_registry(world)
        out = registry.call("no_such_tool", {})
        self.assertFalse(out["ok"])
        self.assertIn("未注册的工具", json.dumps(out["result"], ensure_ascii=False))


class TestMcpServer(unittest.TestCase):
    def test_protocol(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "run.py"), "mcp", "--selftest"],
            capture_output=True, text=True, timeout=120, encoding="utf-8", cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("SELFTEST: PASS", proc.stdout)


class TestCliEndToEnd(unittest.TestCase):
    def test_mock_run_completes(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "run.py"), "cli", "--mode", "mock"],
            capture_output=True, text=True, timeout=300, encoding="utf-8", cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("状态: completed", proc.stdout)
        self.assertIn("报告:", proc.stdout)


class TestHttpService(unittest.TestCase):
    def test_state_and_run(self):
        port = 8799
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "run.py"), "web", "--port", str(port), "--no-browser"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", cwd=ROOT,
        )
        base = "http://127.0.0.1:%d" % port
        try:
            self._wait_service(base)
            state = self._get(base + "/api/state")
            self.assertIn("devices", state)
            self.assertIn("run", state)

            self._post(base + "/api/run", {"mode": "mock"})
            deadline = time.time() + 180
            final = None
            while time.time() < deadline:
                final = self._get(base + "/api/state")
                if final["run"]["status"] in ("completed", "max_steps_reached", "aborted"):
                    break
                time.sleep(1)
            self.assertEqual(final["run"]["status"], "completed")
            trace = final["run"]["trace"]
            self.assertTrue(trace["report"])
            self.assertEqual(final["devices"]["VALVE-01"]["state"]["open"], False)
            self.assertEqual(final["devices"]["VENT-01"]["state"]["level"], 100)
            self.assertTrue(final["evacuated"])
            self.assertLessEqual(final["field_ppm"], final["thresholds"]["safe_ppm"])
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _wait_service(self, base, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            try:
                self._get(base + "/api/state")
                return
            except Exception:
                time.sleep(0.5)
        raise AssertionError("服务未在 %ss 内就绪" % timeout)

    def _get(self, url):
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _post(self, url, payload):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
