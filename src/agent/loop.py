"""内置 Agent Loop：与 AGH 同构的「模型决策—工具执行—反馈回灌」循环。

每一步都落 Trace，任何工具异常都作为观测回传模型，由模型自行决定重试或换方案，
不使用兜底静默成功。
"""

import time

from src.agent.planner import RulePlanner
from src.llm.client import AgnesClient, LLMError, extract_tool_call
from src.trace import Trace

PHASE_BY_TOOL = {
    "get_sensor_readings": "P1 感知",
    "get_device_status": "P1 感知",
    "read_environment": "P1 感知",
    "get_camera_frame": "P2 确认",
    "move_robot": "P2 确认",
    "robot_measure": "P2 确认",
    "close_gas_valve": "P3 切断",
    "arm_manual_shutoff": "P3 切断",
    "set_ventilation": "P4 控制",
    "activate_alarm": "P4 控制",
    "broadcast_message": "P4 控制",
    "unlock_exits": "P4 控制",
    "wait_and_observe": "P5 复核",
    "submit_report": "P6 收尾",
}


def wait_for_alarm(world, timeout_sec=120):
    """监测阶段：等待任一探测器达到预警及以上等级，模拟真实系统的报警触发。"""
    waited = 0.0
    while waited < timeout_sec:
        for dev in world.devices.values():
            if dev.kind == "gas_sensor" and dev.state.get("level") in ("warn", "alarm", "danger"):
                world.events.append({
                    "t": round(world.t, 1), "type": "alarm",
                    "text": "%s 报%s（%.0f ppm），触发应急处置任务" % (dev.id, dev.state["level"], dev.state["ppm"]),
                })
                return dev
        time.sleep(0.2)
        waited += 0.2
    return None


class AgentLoop:
    def __init__(self, world, tools, cfg, mode="builtin", on_step=None):
        self.world = world
        self.tools = tools
        self.cfg = cfg
        self.mode = mode
        self.on_step = on_step
        self.trace = Trace()
        self.llm = AgnesClient(cfg)
        self.planner = RulePlanner(world, tools)
        self.messages = []
        # 模型不可用（未配 Key / 鉴权失败 / 网络不可达）时自动降级，保证演示不中断
        self.llm_down = False
        self.llm_error = None
        # 网关要求 tool 消息必须回填 tool_call_id，否则报 missing field `tool_call_id`
        self._pending_call_id = None

    def _fallback(self, reason, last_result=None):
        if not self.llm_down:
            self.llm_down = True
            self.llm_error = reason
            self.world.events.append({
                "t": round(self.world.t, 1), "type": "llm_fallback",
                "text": "模型不可用，已自动降级为内置规则规划器：%s" % reason,
            })
        return self.planner.next_action(last_result)

    # ---------- 单步决策 ----------
    def decide(self, last_result=None):
        if self.mode == "mock" or not self.llm.available() or self.llm_down:
            return self.planner.next_action(last_result)

        try:
            response = self.llm.chat(self.messages, self.tools.schemas())
            call = extract_tool_call(response)
            msg = response["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")
            self._pending_call_id = (tool_calls[0].get("id") if tool_calls else None)
            self.messages.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": tool_calls,
            })
            if not call.get("name"):
                # 若网关返回了 tool_calls 却没解析出工具名，先回填一条工具回执，
                # 避免「 assistant(tool_calls) 后面直接跟 user 」这种非法序列
                if tool_calls:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": self._pending_call_id,
                        "name": (tool_calls[0].get("function") or {}).get("name") or "unknown",
                        "content": _dump({"ok": False, "error": "工具未执行，请改用 JSON 输出工具名与参数"}),
                    })
                    self._pending_call_id = None

                # 模型未给出工具调用，要求其严格按格式输出，最多纠偏一次
                self.messages.append({
                    "role": "user",
                    "content": "请严格输出 JSON：{\"thought\": \"...\", \"tool\": \"工具名\", \"args\": {...}}，只调用一个工具。",
                })
                response = self.llm.chat(self.messages, self.tools.schemas())
                call = extract_tool_call(response)
            return call
        except LLMError as exc:
            return self._fallback(str(exc), last_result)

    def push_observation(self, tool_name, result):
        if self.mode == "mock" or not self.llm.available() or self.llm_down:
            return
        message = {"role": "tool", "name": tool_name, "content": _dump(result)}
        if self._pending_call_id:
            message["tool_call_id"] = self._pending_call_id
            self._pending_call_id = None
        self.messages.append(message)

    # ---------- 主循环 ----------
    def run(self, max_steps=None):
        from src.agent.prompts import build_messages
        from src.tools.lab_tools import scenario_hints

        max_steps = max_steps or self.cfg["agent"]["max_steps"]
        self.messages = build_messages(self.world.snapshot(), scenario_hints(self.world))

        last_result = None
        for _ in range(max_steps):
            call = self.decide(last_result)
            name = call.get("name")
            if not name:
                self.trace.finish("aborted", None)
                break

            started = time.time()
            outcome = self.tools.call(name, call.get("args"))
            duration_ms = int((time.time() - started) * 1000)

            step = self.trace.add_step(
                phase=PHASE_BY_TOOL.get(name, "其他"),
                thought=call.get("thought", ""),
                tool=name,
                args=call.get("args", {}),
                result=outcome["result"],
                duration_ms=outcome.get("duration_ms", duration_ms),
                ok=outcome["ok"],
            )
            step["wall_clock"] = round(time.time() - self.trace.started_at, 2)

            if self.on_step:
                self.on_step(step)

            last_result = outcome["result"]
            self.push_observation(name, outcome["result"])

            if name == "submit_report" and outcome["ok"]:
                self.trace.finish("completed", outcome["result"]["report"])
                break
        else:
            self.trace.finish("max_steps_reached", None)

        return self.trace


def _dump(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)[:4000]
