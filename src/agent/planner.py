"""离线规则规划器（Mock 模式）。

严格实现与 SOP 提示词一致的决策链，用于无 Key / 无网络环境下的完整演练与回归测试；
接入真实模型后由模型接管决策，本规划器退化为基线对照。
"""


class RulePlanner:
    def __init__(self, world, tools):
        self.world = world
        self.tools = tools
        self.stage = 0
        self.alarm_seen = False
        self.valve_closed = False
        self.shutoff_failed = False
        self.vent_on = False
        self.alarm_on = False
        self.evacuated = False
        self.observe_count = 0
        self.confirmed = False

    def next_action(self, last_result=None):
        w = self.world
        ppm = w.concentration_at(w.source)

        if self.stage == 0:
            self.stage = 1
            return self._act("按 SOP 先全面感知现场气体浓度", "get_sensor_readings", {})

        if self.stage == 1:
            self.stage = 2
            self.alarm_seen = ppm >= w.thresholds["warn_ppm"]
            return self._act(
                "单点读数需交叉验证，调取气瓶间摄像机画面确认是否存在可见异常",
                "get_camera_frame", {"camera_id": "CAM-01"},
            )

        if self.stage == 2:
            self.stage = 3
            return self._act(
                "派巡检机器人前往气瓶间（泄漏源点位）做现场复测",
                "move_robot", {"robot_id": "R-01", "x": 2.0, "y": 6.0},
            )

        if self.stage == 3:
            self.stage = 4
            self.confirmed = True
            return self._act("机器人已就位，现场实测浓度以排除误报", "robot_measure", {"robot_id": "R-01"})

        if self.stage == 4:
            self.stage = 5
            return self._act("确认真实泄漏，远程关闭乙炔汇流排电磁阀", "close_gas_valve", {"valve_id": "VALVE-01"})

        if self.stage == 5:
            failed = not (last_result or {}).get("ok", False)
            if failed:
                self.shutoff_failed = True
                self.stage = 6
                return self._act("远程关阀失败，改派机械臂 ARM-01 就地手动关阀", "arm_manual_shutoff",
                                 {"arm_id": "ARM-01", "valve_id": "VALVE-01"})
            self.valve_closed = True
            self.stage = 7
            return self._act("阀门已远程关闭，启动事故排风至 100%", "set_ventilation", {"level": 100})

        if self.stage == 6:
            self.valve_closed = True
            self.stage = 7
            return self._act("阀门已手动关闭，启动事故排风至 100%", "set_ventilation", {"level": 100})

        if self.stage == 7:
            self.vent_on = True
            self.stage = 8
            return self._act("排风已启动，启动声光报警器警示现场", "activate_alarm", {})

        if self.stage == 8:
            self.alarm_on = True
            self.stage = 9
            return self._act("广播疏散指令，引导人员撤离", "broadcast_message",
                             {"message": "实验室发生乙炔泄漏，请立即沿安全出口撤离，切勿使用电梯"})

        if self.stage == 9:
            self.stage = 10
            return self._act("解锁全部安全出口闸机，保障疏散通道", "unlock_exits", {})

        if self.stage == 10:
            self.evacuated = True
            self.stage = 11
            self.observe_count = 1
            return self._act("处置动作已完成，观测 12 秒确认浓度下降趋势", "wait_and_observe", {"seconds": 12})

        if self.stage == 11:
            safe = ppm <= w.thresholds["safe_ppm"]
            if safe or self.observe_count >= 3:
                self.stage = 12
                return self._act(
                    "浓度已降至安全阈值以下，处置闭环，提交事故报告" if safe else "达到最大观测轮次，据实提交报告",
                    "submit_report", self._report(ppm, safe),
                )
            self.observe_count += 1
            return self._act(
                "当前浓度 %.1f ppm 仍高于安全线 %s ppm，继续观测" % (ppm, w.thresholds["safe_ppm"]),
                "wait_and_observe", {"seconds": 10},
            )

        return None

    def _report(self, ppm, safe):
        w = self.world
        actions = [
            "读取三路可燃气体探测器并识别 S-01 超限报警",
            "调取 CAM-01 画面交叉验证，排除单点误报",
            "调度巡检机器人 R-01 至气瓶间现场复测",
            "远程关闭 VALVE-01 电磁阀（执行器无响应，失败）" if self.shutoff_failed else "远程关闭 VALVE-01 电磁阀",
        ]
        if self.shutoff_failed:
            actions.append("派机械臂 ARM-01 就地手动关闭 VALVE-01")
        actions += [
            "启动事故排风系统至 100% 档",
            "启动声光报警器并广播疏散指令",
            "解锁全部安全出口闸机，人员疏散完成",
            "持续观测浓度直至降至安全阈值" if safe else "多轮观测，浓度仍未完全达标",
        ]
        return {
            "summary": "%s发生乙炔泄漏事故，Agent 按 SOP 完成确认—切断—控制—复核闭环，"
                       "最终源点浓度 %.1f ppm（%s）。" % (w.name, ppm, "已达标" if safe else "未达标，需人工介入"),
            "root_cause": "气瓶间乙炔汇流排密封件老化失效导致泄漏；电磁阀电动执行器存在反馈超时故障，"
                          "远程关阀不可用，构成单点失效风险。",
            "actions": actions,
            "recommendations": [
                "更换汇流排密封件并纳入季度强制点检",
                "修复 VALVE-01 电动执行器，增设手动关阀冗余与状态反馈回路",
                "在气瓶间增设独立的可燃气体探测回路，避免单点误报/漏报",
                "将本次处置流程固化为 Agnes Harness Skill，跨实验室复用",
            ],
        }

    def _act(self, thought, tool, args):
        return {"name": tool, "args": args, "thought": thought}
