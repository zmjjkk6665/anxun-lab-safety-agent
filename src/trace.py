"""执行轨迹（Trace）：对齐 AGH Trace 页面的可观测模型。

每一步记录：思考 / 工具 / 入参 / 返回 / 耗时 / 状态，供前端时间轴回放与事后复盘。
"""

import json
import os
import time


class Trace:
    def __init__(self, task_id=None):
        self.task_id = task_id or time.strftime("task-%Y%m%d-%H%M%S")
        self.started_at = time.time()
        self.steps = []
        self.status = "running"
        self.final_report = None

    def add_step(self, phase, thought, tool, args, result, duration_ms, ok=True):
        step = {
            "index": len(self.steps) + 1,
            "phase": phase,
            "thought": thought,
            "tool": tool,
            "args": args or {},
            "result": result,
            "duration_ms": duration_ms,
            "ok": ok,
            "wall_clock": round(time.time() - self.started_at, 2),
            "sim_clock": None,
        }
        self.steps.append(step)
        return step

    def finish(self, status="completed", report=None):
        self.status = status
        if report:
            self.final_report = report

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.started_at)),
            "elapsed_sec": round(time.time() - self.started_at, 2),
            "steps": self.steps,
            "report": self.final_report,
        }

    def save(self, directory):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, "%s.json" % self.task_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return path
