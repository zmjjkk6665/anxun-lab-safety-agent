"""实验室数字孪生仿真引擎。

提供 9 类 MHS 设备的行为模型与乙炔泄漏扩散模型，可在无实体硬件下驱动
完整的应急处置演练。所有设备对外暴露统一状态字典，便于 MHS 协议映射。
"""

import math
import random
import threading
import time

LAB_WIDTH = 12.0
LAB_HEIGHT = 8.0

# 关键点位（米）
POS_CYLINDER = (2.0, 6.0)     # 气瓶间 / 汇流排
POS_HOOD = (6.0, 3.0)         # 通风橱
POS_CABINET = (9.0, 2.0)      # 溶剂柜
POS_EXIT = (11.0, 1.0)        # 安全出口
POS_HOME = (1.0, 1.0)         # 机器人待机位


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Device:
    """设备基类：统一 id / 类型 / 位置 / 状态 / 能力描述（MHS 自描述信息）。"""

    kind = "device"

    def __init__(self, dev_id, name, pos, capabilities):
        self.id = dev_id
        self.name = name
        self.pos = tuple(pos)
        self.capabilities = list(capabilities)
        self.status = "online"
        self.state = {}
        self.note = ""

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "pos": {"x": self.pos[0], "y": self.pos[1]},
            "status": self.status,
            "capabilities": self.capabilities,
            "state": dict(self.state),
            "note": self.note,
        }


class GasSensor(Device):
    kind = "gas_sensor"

    def __init__(self, dev_id, name, pos, world, bias=0.0):
        super().__init__(dev_id, name, pos, ["read_concentration", "read_status"])
        self.world = world
        self.bias = bias
        self.state = {"ppm": 0.0, "level": "normal"}

    def read(self):
        ppm = self.world.concentration_at(self.pos) + self.bias + random.uniform(-8, 8)
        ppm = max(0.0, ppm)
        th = self.world.thresholds
        if ppm >= th["danger_ppm"]:
            level = "danger"
        elif ppm >= th["alarm_ppm"]:
            level = "alarm"
        elif ppm >= th["warn_ppm"]:
            level = "warn"
        else:
            level = "normal"
        self.state = {"ppm": round(ppm, 1), "level": level}
        return dict(self.state)


class Camera(Device):
    kind = "camera"

    def __init__(self, dev_id, name, pos, world):
        super().__init__(dev_id, name, pos, ["capture_frame", "detect_smoke_flame", "count_people"])
        self.world = world
        self.state = {"people": 2, "smoke": False, "flame": False}

    def capture(self):
        w = self.world
        near = w.concentration_at(self.pos)
        smoke = near >= w.thresholds["warn_ppm"] * 0.6
        flame = w.ignition
        people = w.occupants if not w.evacuated else 0
        self.state = {"people": people, "smoke": smoke, "flame": flame}
        return {
            "camera": self.id,
            "people": people,
            "smoke": smoke,
            "flame": flame,
            "description": "画面可见%s%s，现场%s人" % (
                "明火" if flame else ("疑似白雾/烟雾" if smoke else "无异常"),
                "" if flame else "",
                people,
            ),
        }


class ThermoHygrometer(Device):
    kind = "thermo"

    def __init__(self, dev_id, name, pos, world):
        super().__init__(dev_id, name, pos, ["read_temp_humidity"])
        self.world = world
        self.state = {"temp": 24.5, "humidity": 48.0}

    def read(self):
        extra = 0.0
        if self.world.ignition:
            extra = 6.0
        self.state = {
            "temp": round(24.5 + extra + random.uniform(-0.3, 0.3), 1),
            "humidity": round(48.0 + random.uniform(-1, 1), 1),
        }
        return dict(self.state)


class GasValve(Device):
    kind = "gas_valve"

    def __init__(self, dev_id, name, pos, world, actuator_fault=False):
        super().__init__(dev_id, name, pos, ["close", "open", "read_status"])
        self.world = world
        self.actuator_fault = actuator_fault
        self.state = {"open": True, "actuator": "fault" if actuator_fault else "ok"}

    def close(self):
        if self.actuator_fault:
            self.status = "fault"
            self.state["last_action"] = "close_failed"
            return {
                "ok": False,
                "reason": "电动执行器无响应（反馈超时），远程关阀失败，需机械臂就地手动关阀",
            }
        self.state["open"] = False
        self.state["last_action"] = "closed_remote"
        return {"ok": True, "state": "closed"}

    def manual_close(self, by):
        self.state["open"] = False
        self.state["last_action"] = "closed_manual_by_%s" % by
        self.status = "online"
        return {"ok": True, "state": "closed", "operator": by}


class Ventilation(Device):
    kind = "ventilation"

    def __init__(self, dev_id, name, pos, world):
        super().__init__(dev_id, name, pos, ["set_level", "read_status"])
        self.world = world
        self.state = {"level": 0, "running": False}

    def set_level(self, level):
        level = int(max(0, min(100, level)))
        self.state = {"level": level, "running": level > 0}
        return {"ok": True, "level": level}


class PatrolRobot(Device):
    kind = "patrol_robot"

    def __init__(self, dev_id, name, pos, world, speed=1.6):
        super().__init__(dev_id, name, pos, ["move_to", "measure_gas", "broadcast", "read_status"])
        self.world = world
        self.speed = speed
        self.target = None
        self.state = {"pos": list(pos), "battery": 92, "moving": False}

    def move_to(self, target):
        self.target = tuple(target)
        self.state["moving"] = True
        return {"ok": True, "target": list(self.target)}

    def measure_gas(self):
        return {
            "robot": self.id,
            "ppm": round(self.world.concentration_at(tuple(self.state["pos"])), 1),
            "pos": [round(v, 2) for v in self.state["pos"]],
        }

    def broadcast(self, message):
        self.world.events.append({"t": round(self.world.t, 1), "type": "broadcast", "text": message})
        return {"ok": True, "message": message}


class RobotArm(Device):
    kind = "robot_arm"

    def __init__(self, dev_id, name, pos, world, reach=3.0):
        super().__init__(dev_id, name, pos, ["manual_shutoff", "deploy_fire_blanket", "read_status"])
        self.world = world
        self.reach = reach
        self.state = {"pose": "idle", "holding": None}

    def manual_shutoff(self, valve):
        d = dist(self.pos, valve.pos)
        if d > self.reach:
            return {"ok": False, "reason": "目标超出机械臂可达范围 (%.1fm > %.1fm)" % (d, self.reach)}
        self.state = {"pose": "grip_close", "holding": valve.id}
        return valve.manual_close(by=self.id)

    def deploy_fire_blanket(self):
        self.state = {"pose": "blanket", "holding": "fire_blanket"}
        return {"ok": True, "deployed": True}


class SirenAlarm(Device):
    kind = "siren"

    def __init__(self, dev_id, name, pos, world):
        super().__init__(dev_id, name, pos, ["activate", "deactivate"])
        self.world = world
        self.state = {"active": False}

    def activate(self):
        self.state = {"active": True}
        return {"ok": True, "active": True}

    def deactivate(self):
        self.state = {"active": False}
        return {"ok": True, "active": False}


class ExitDoor(Device):
    kind = "exit_door"

    def __init__(self, dev_id, name, pos, world):
        super().__init__(dev_id, name, pos, ["unlock_all", "read_status"])
        self.world = world
        self.state = {"locked": True}

    def unlock_all(self):
        self.state = {"locked": False}
        self.world.evacuated = True
        return {"ok": True, "locked": False, "evacuated": True}


class LabWorld:
    """实验室世界模型：时间推进 + 泄漏扩散 + 设备联动 + 事件流。"""

    def __init__(self, cfg):
        lab = cfg["lab"]
        self.name = lab["name"]
        self.chemical = lab["chemical"]
        self.thresholds = dict(cfg["thresholds"])
        self.speed = float(lab.get("sim_speed", 1.0))
        self.leak_start_sec = float(lab.get("leak_start_sec", 10.0))

        self.lock = threading.RLock()
        self.t = 0.0
        self.running = False
        self.leak_active = False
        self.ignition = False
        self.evacuated = False
        self.occupants = 2
        self.field = 0.0          # 泄漏源强度（源点 ppm）
        self.source = POS_CYLINDER
        self.leak_rate = 120.0    # ppm/s
        self.events = []

        self.devices = {}
        self._build_devices()

    def _build_devices(self):
        th = self.thresholds
        self.vent = Ventilation("VENT-01", "事故排风系统", (6.0, 4.0), self)
        self.valve = GasValve("VALVE-01", "乙炔汇流排电磁阀", POS_CYLINDER, self, actuator_fault=True)
        self.arm = RobotArm("ARM-01", "应急处置机械臂", (3.0, 6.0), self, reach=3.0)
        self.robot = PatrolRobot("R-01", "巡检机器人", POS_HOME, self)
        for d in [
            GasSensor("S-01", "气瓶间可燃气体探测器", POS_CYLINDER, self),
            GasSensor("S-02", "通风橱可燃气体探测器", POS_HOOD, self, bias=15.0),
            GasSensor("S-03", "溶剂柜可燃气体探测器", POS_CABINET, self),
            Camera("CAM-01", "气瓶间摄像机", POS_CYLINDER, self),
            Camera("CAM-02", "实验区全景摄像机", (8.0, 4.0), self),
            ThermoHygrometer("TH-01", "温湿度变送器", (6.0, 5.0), self),
            self.vent,
            self.valve,
            self.arm,
            self.robot,
            SirenAlarm("ALM-01", "声光报警器", POS_EXIT, self),
            ExitDoor("DOOR-01", "安全出口闸机", POS_EXIT, self),
        ]:
            self.devices[d.id] = d
        # 阈值信息挂到 world 便于传感器读取
        self.threshold_hint = th

    # ---------- 仿真推进 ----------
    def concentration_at(self, pos):
        with self.lock:
            if self.field <= 0:
                return 0.0
            d = dist(pos, self.source)
            return self.field * math.exp(-d / 3.0)

    def tick(self, dt):
        with self.lock:
            self.t += dt
            if not self.leak_active and self.t >= self.leak_start_sec:
                self.leak_active = True
                self.events.append({
                    "t": round(self.t, 1), "type": "fault",
                    "text": "%s汇流排密封失效，发生泄漏（剧本注入）" % self.chemical,
                })

            # 质量守恒式浓度演化：泄漏源项 - 一阶通风稀释 - 绝对沉降。
            # 泄漏期间同样参与衰减，因此浓度存在稳态上限，不会随演练时长无限累积。
            emitting = self.leak_active and self.valve.state.get("open", True)
            source = self.leak_rate if emitting else 0.0
            vent_k = 0.05 + 0.0012 * self.vent.state["level"]   # 1/s：自然渗透 + 机械排风
            self.field = max(0.0, self.field + (source - vent_k * self.field - 20.0) * dt)

            if self.field >= self.thresholds["danger_ppm"] * 1.6 and not self.ignition:
                self.ignition = True
                self.events.append({"t": round(self.t, 1), "type": "ignition", "text": "浓度达到危险阈值，出现明火"})

            # 机器人移动
            rb = self.robot
            if rb.target:
                cur = tuple(rb.state["pos"])
                tgt = rb.target
                d = dist(cur, tgt)
                step = rb.speed * dt
                if d <= step or d < 0.15:
                    rb.state["pos"] = list(tgt)
                    rb.target = None
                    rb.state["moving"] = False
                else:
                    rb.state["pos"] = [
                        cur[0] + (tgt[0] - cur[0]) * step / d,
                        cur[1] + (tgt[1] - cur[1]) * step / d,
                    ]
                rb.state["battery"] = max(5, rb.state["battery"] - dt * 0.05)

            for dev in self.devices.values():
                if isinstance(dev, GasSensor):
                    dev.read()

    def start(self):
        if self.running:
            return
        self.running = True

        def loop():
            last = time.time()
            while self.running:
                now = time.time()
                dt = (now - last) * self.speed
                last = now
                if dt > 0:
                    self.tick(min(dt, 2.0))
                time.sleep(0.1)

        t = threading.Thread(target=loop, daemon=True)
        t.start()

    def stop(self):
        self.running = False

    # ---------- 快照 ----------
    def snapshot(self):
        with self.lock:
            return {
                "t": round(self.t, 1),
                "lab": self.name,
                "chemical": self.chemical,
                "leak_active": self.leak_active,
                "ignition": self.ignition,
                "evacuated": self.evacuated,
                "occupants": 0 if self.evacuated else self.occupants,
                "field_ppm": round(self.field, 1),
                "thresholds": dict(self.thresholds),
                "devices": {k: v.to_dict() for k, v in self.devices.items()},
                "events": list(self.events[-30:]),
            }

    def get(self, dev_id):
        dev = self.devices.get(dev_id)
        if not dev:
            raise KeyError("未知设备: %s" % dev_id)
        return dev
