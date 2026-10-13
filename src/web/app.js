// 前端大屏：轮询 /api/state 渲染实验室态势、Agent 轨迹与处置报告。
const SCALE = 52;      // 1 米 = 52 px
const PAD = 20;

const el = (id) => document.getElementById(id);
const toPx = (x, y) => ({ cx: PAD + x * SCALE, cy: PAD + (8 - y) * SCALE });

function initStatic() {
  const grid = el("grid");
  let g = "";
  for (let x = 0; x <= 12; x++) g += `<line x1="${PAD + x * SCALE}" y1="${PAD}" x2="${PAD + x * SCALE}" y2="${PAD + 8 * SCALE}" stroke="#1b2740"/>`;
  for (let y = 0; y <= 8; y++) g += `<line x1="${PAD}" y1="${PAD + y * SCALE}" x2="${PAD + 12 * SCALE}" y2="${PAD + y * SCALE}" stroke="#1b2740"/>`;
  grid.innerHTML = g;

  el("zones").innerHTML = [
    { name: "气瓶间", x: 1, y: 5, w: 2.4, h: 2.2, color: "#2a1d1d" },
    { name: "通风橱区", x: 4.8, y: 2, w: 2.6, h: 2.0, color: "#1b2233" },
    { name: "溶剂柜", x: 8, y: 1.2, w: 1.8, h: 1.6, color: "#1b2233" },
    { name: "安全出口", x: 10, y: 0.4, w: 1.6, h: 1.2, color: "#172a20" },
  ].map((z) => {
    const p = toPx(z.x, z.y + z.h);
    return `<rect x="${p.cx}" y="${p.cy}" width="${z.w * SCALE}" height="${z.h * SCALE}" fill="${z.color}" stroke="#2b3b5c" rx="6"/>
            <text x="${p.cx + 8}" y="${p.cy + 18}" fill="#8a9bb5" font-size="12">${z.name}</text>`;
  }).join("");
}

const KIND_LABEL = {
  gas_sensor: "探测器", camera: "摄像机", thermo: "温湿度", gas_valve: "电磁阀",
  ventilation: "排风", patrol_robot: "巡检机器人", robot_arm: "机械臂", siren: "报警器", exit_door: "出口闸机",
};

function levelClass(state, dev) {
  if (dev.status === "fault") return "fault";
  if (dev.kind === "gas_sensor") return state.level || "normal";
  if (dev.kind === "gas_valve") return state.open ? "alarm" : "ok";
  if (dev.kind === "ventilation") return state.running ? "ok" : "fault";
  if (dev.kind === "siren") return state.active ? "danger" : "fault";
  if (dev.kind === "exit_door") return state.locked ? "fault" : "ok";
  return dev.status === "online" ? "ok" : "fault";
}

function renderMap(state) {
  const markers = el("markers");
  markers.innerHTML = Object.values(state.devices)
    .filter((d) => d.kind !== "patrol_robot")
    .map((d) => {
      const p = toPx(d.pos.x, d.pos.y);
      const cls = levelClass(d.state, d);
      const color = { ok: "#37d67a", warn: "#f7c948", alarm: "#ff9f43", danger: "#ff4d4f", fault: "#7a8699" }[cls];
      return `<g>
        <circle cx="${p.cx}" cy="${p.cy}" r="9" fill="${color}" opacity="0.25"/>
        <circle cx="${p.cx}" cy="${p.cy}" r="5" fill="${color}" stroke="#0b1322"/>
        <text x="${p.cx + 11}" y="${p.cy + 4}" fill="#c8d6ea" font-size="11">${d.id} ${KIND_LABEL[d.kind] || d.kind}</text>
      </g>`;
    }).join("");

  const rb = state.devices["R-01"];
  if (rb) {
    const p = toPx(rb.state.pos[0], rb.state.pos[1]);
    el("robot").innerHTML = `<rect x="${p.cx - 9}" y="${p.cy - 9}" width="18" height="18" rx="5" fill="#3f8cff"/>
      <text x="${p.cx + 12}" y="${p.cy + 4}" fill="#3f8cff" font-size="11">R-01${rb.state.moving ? " 行进中" : ""}</text>`;
  }

  const leak = el("leak");
  const src = toPx(2, 6);
  const ppm = state.field_ppm;
  leak.setAttribute("cx", src.cx);
  leak.setAttribute("cy", src.cy);
  leak.setAttribute("r", String(Math.min(160, 20 + ppm / 8)));
  leak.setAttribute("opacity", state.leak_active ? String(Math.min(0.95, 0.15 + ppm / 1500)) : "0");
}

function renderKpis(state) {
  el("clock").textContent = "T+" + state.t.toFixed(1) + "s";
  el("lab-name").textContent = state.lab + " · " + state.chemical;
  el("kpi-ppm").textContent = state.field_ppm.toFixed(1);
  const vent = state.devices["VENT-01"], valve = state.devices["VALVE-01"];
  el("kpi-vent").textContent = vent ? vent.state.level : 0;
  el("kpi-valve").textContent = valve ? (valve.state.open ? "开" : "关") : "-";
  el("kpi-people").textContent = state.occupants;
}

function renderSensors(state) {
  el("sensors").innerHTML = Object.values(state.devices)
    .filter((d) => d.kind === "gas_sensor")
    .map((d) => {
      const lvl = d.state.level || "normal";
      const pct = Math.min(100, (d.state.ppm / state.thresholds.danger_ppm) * 100);
      return `<div class="sensor ${lvl}">
        <div class="row"><b>${d.id}</b><span>${d.state.ppm} ppm · ${lvl}</span></div>
        <div class="muted" style="font-size:11px">${d.name}</div>
        <div class="bar"><i style="width:${pct}%"></i></div>
      </div>`;
    }).join("");
}

function renderDevices(state) {
  el("devices").innerHTML = Object.values(state.devices)
    .filter((d) => !["gas_sensor"].includes(d.kind))
    .map((d) => `<div class="device ${d.status === "fault" ? "fault" : ""}">
        <span>${d.id} ${KIND_LABEL[d.kind] || d.kind}</span>
        <span class="muted">${(d.state.last_action || d.status || "").toString()}</span>
      </div>`).join("");
}

function renderTrace(run) {
  const tag = el("mode-tag");
  tag.textContent = run.status === "running" ? "处置中" : (run.status === "completed" ? "处置完成" : run.status);
  tag.className = "tag " + (run.status === "completed" ? "completed" : run.status === "running" ? "running" : "");

  const steps = (run.trace && run.trace.steps) || [];
  el("trace").innerHTML = steps.length
    ? steps.map((s) => `<div class="step ${s.ok ? "" : "bad"}">
        <div class="idx">#${s.index}</div>
        <div class="phase">${s.phase}</div>
        <div>
          <div><span class="tool">${s.tool}</span>
            <span class="ms">${s.duration_ms} ms · T+${s.wall_clock}s</span></div>
          <div class="thought">${s.thought || ""}</div>
          <div class="res">${JSON.stringify(s.result).slice(0, 260)}</div>
        </div>
      </div>`).join("")
    : `<div class="muted">未启动。点击「启动应急处置」，Agent 将通过工具调用完成 感知→确认→切断→控制→复核→报告 全流程。</div>`;

  const rep = run.trace && run.trace.report;
  el("report").innerHTML = rep
    ? `<h4>结论</h4><div>${rep.summary}</div>
       <h4>根因分析</h4><div>${rep.root_cause}</div>
       <h4>处置动作</h4><ul>${rep.actions.map((a) => `<li>${a}</li>`).join("")}</ul>
       <h4>整改建议</h4><ul>${(rep.recommendations || []).map((a) => `<li>${a}</li>`).join("")}</ul>`
    : `<span class="muted">尚未生成，等待处置闭环。</span>`;
}

async function poll() {
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    renderMap(state); renderKpis(state); renderSensors(state); renderDevices(state); renderTrace(state.run);
  } catch (e) {
    el("trace").innerHTML = `<div class="muted">服务未响应：${e}</div>`;
  }
  setTimeout(poll, 700);
}

el("btn-run").onclick = async () => {
  const r = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
  const j = await r.json();
  if (!j.started) alert("未能启动：" + (j.reason || "未知原因"));
};
el("btn-reset").onclick = () => fetch("/api/reset", { method: "POST" });

initStatic();
poll();
