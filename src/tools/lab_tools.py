"""应急处置工具集：Agent 通过这些函数感知现场并操控设备。

每个工具都是真实作用于 LabWorld 的副作用操作，返回值直接作为观测反馈给模型。
"""

import time

from src.tools.registry import ToolRegistry
from src.world import POS_CYLINDER, POS_EXIT, POS_HOOD


def build_registry(world):
    """绑定世界实例，生成工具注册表。"""
    registry = ToolRegistry()

    @registry.register(
        description="读取全部可燃气体探测器读数（ppm）与报警等级",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_sensor_readings():
        readings = {}
        for dev in world.devices.values():
            if dev.kind == "gas_sensor":
                readings[dev.id] = dev.read()
        return {"readings": readings, "chemical": world.chemical, "t": round(world.t, 1)}

    @registry.register(
        description="获取所有设备的状态、位置与能力清单",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def get_device_status():
        return {"devices": {k: v.to_dict() for k, v in world.devices.items()}}

    @registry.register(
        description="调取摄像机画面分析结果：人数、是否有烟雾/明火",
        parameters={
            "type": "object",
            "properties": {"camera_id": {"type": "string", "description": "摄像机ID，如 CAM-01"}},
            "required": ["camera_id"],
        },
    )
    def get_camera_frame(camera_id: str):
        dev = world.get(camera_id)
        if dev.kind != "camera":
            return {"ok": False, "error": "%s 不是摄像机" % camera_id}
        return dev.capture()

    @registry.register(
        description="派巡检机器人移动到指定坐标，返回是否到位",
        parameters={
            "type": "object",
            "properties": {
                "robot_id": {"type": "string"},
                "x": {"type": "number"},
                "y": {"type": "number"},
            },
            "required": ["robot_id", "x", "y"],
        },
    )
    def move_robot(robot_id: str, x: float, y: float):
        dev = world.get(robot_id)
        if dev.kind != "patrol_robot":
            return {"ok": False, "error": "%s 不是巡检机器人" % robot_id}
        dev.move_to((x, y))
        deadline = time.time() + 60
        while time.time() < deadline:
            if not dev.state.get("moving"):
                return {"ok": True, "arrived": True, "pos": [round(v, 2) for v in dev.state["pos"]]}
            time.sleep(0.2)
        return {"ok": False, "error": "移动超时", "pos": dev.state["pos"]}

    @registry.register(
        description="让巡检机器人在当前位置现场检测气体浓度",
        parameters={"type": "object", "properties": {"robot_id": {"type": "string"}}, "required": ["robot_id"]},
    )
    def robot_measure(robot_id: str):
        dev = world.get(robot_id)
        return dev.measure_gas()

    @registry.register(
        description="远程关闭燃气管道电磁阀；执行器故障时会返回失败原因",
        parameters={"type": "object", "properties": {"valve_id": {"type": "string"}}, "required": ["valve_id"]},
    )
    def close_gas_valve(valve_id: str):
        dev = world.get(valve_id)
        return dev.close()

    @registry.register(
        description="派机械臂就地手动关阀（远程关阀失败时的兜底手段）",
        parameters={
            "type": "object",
            "properties": {"arm_id": {"type": "string"}, "valve_id": {"type": "string"}},
            "required": ["arm_id", "valve_id"],
        },
    )
    def arm_manual_shutoff(arm_id: str, valve_id: str):
        arm = world.get(arm_id)
        valve = world.get(valve_id)
        return arm.manual_shutoff(valve)

    @registry.register(
        description="设置事故排风系统风量档位（0-100），0 为停止",
        parameters={"type": "object", "properties": {"level": {"type": "integer"}}, "required": ["level"]},
    )
    def set_ventilation(level: int):
        return world.vent.set_level(level)

    @registry.register(
        description="启动声光报警器",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def activate_alarm():
        return world.get("ALM-01").activate()

    @registry.register(
        description="通过巡检机器人广播疏散指令",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
    )
    def broadcast_message(message: str):
        return world.robot.broadcast(message)

    @registry.register(
        description="解锁全部安全出口闸机，完成人员疏散",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def unlock_exits():
        return world.get("DOOR-01").unlock_all()

    @registry.register(
        description="等待并持续观测若干秒，返回浓度变化趋势（用于处置后复核）",
        parameters={"type": "object", "properties": {"seconds": {"type": "number"}}, "required": ["seconds"]},
    )
    def wait_and_observe(seconds: float):
        seconds = max(1.0, min(float(seconds), 30.0))
        start = world.concentration_at(POS_CYLINDER)
        start_t = world.t
        samples = []
        next_sample = start_t + 1.0
        # 按仿真时钟推进，保证倍速调节真实生效
        while world.t - start_t < seconds:
            time.sleep(0.1)
            if world.t >= next_sample:
                samples.append(round(world.concentration_at(POS_CYLINDER), 1))
                next_sample += 1.0
        end = world.concentration_at(POS_CYLINDER)
        return {
            "seconds": round(seconds, 1),
            "elapsed_sim_sec": round(world.t - start_t, 1),
            "start_ppm": round(start, 1),
            "end_ppm": round(end, 1),
            "samples": samples,
            "trend": "down" if end < start else ("flat" if abs(end - start) < 5 else "up"),
        }

    @registry.register(
        description="读取温湿度，用于判断是否存在燃爆风险",
        parameters={"type": "object", "properties": {}, "required": []},
    )
    def read_environment():
        return world.get("TH-01").read()

    @registry.register(
        description="提交最终事故处置报告并结束任务",
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "事故与处置结论概述"},
                "root_cause": {"type": "string", "description": "根因分析"},
                "actions": {"type": "array", "items": {"type": "string"}, "description": "已执行的处置动作列表"},
                "recommendations": {"type": "array", "items": {"type": "string"}, "description": "整改建议"},
            },
            "required": ["summary", "root_cause", "actions"],
        },
    )
    def submit_report(summary: str, root_cause: str, actions: list, recommendations: list = None):
        return {
            "ok": True,
            "report": {
                "summary": summary,
                "root_cause": root_cause,
                "actions": actions,
                "recommendations": recommendations or [],
            },
        }

    return registry


def scenario_hints(world):
    """给模型的关键点位速查，避免其盲目搜索坐标。"""
    return {
        "cylinder_room": {"pos": list(POS_CYLINDER), "desc": "气瓶间/汇流排，泄漏源"},
        "fume_hood": {"pos": list(POS_HOOD), "desc": "通风橱"},
        "exit": {"pos": list(POS_EXIT), "desc": "安全出口"},
    }
