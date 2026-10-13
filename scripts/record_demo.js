/**
 * 自动录制演示视频：用系统 Edge（Playwright CDP）驱动大屏，播放一次真实应急处置并录屏。
 *
 * 用法：
 *   npm i playwright-core
 *   node scripts/record_demo.js                  # 真机模式（需 AGNES_API_KEY）
 *   node scripts/record_demo.js --mode mock      # 离线模式（快、稳定）
 *   node scripts/record_demo.js --seconds 60     # 最长录制时长
 *
 * 输出：outputs/video/演示视频-安巡-实验室安全应急处置.webm
 * 说明：视频内叠加中文字幕条与片头，无需配音即可看懂；全程不显示任何模型 Key。
 */

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const EDGE = process.env.EDGE_PATH ||
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const BASE = process.env.DEMO_URL || 'http://127.0.0.1:8787/';

const argv = process.argv.slice(2);
const getArg = (name, def) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : def;
};
const MODE = getArg('--mode', 'auto');
const MAX_SEC = Number(getArg('--seconds', '300'));

const ROOT = path.resolve(__dirname, '..');
const VIDEO_DIR = path.join(ROOT, 'outputs', 'video');

const CAPTION_CSS = `
  #demo-caption {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 9999;
    background: linear-gradient(180deg, rgba(8,14,26,0) 0%, rgba(8,14,26,.92) 22%);
    padding: 26px 34px 22px; font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    color: #e8f0ff; pointer-events: none;
  }
  #demo-caption .cap-phase {
    display: inline-block; font-size: 15px; letter-spacing: 1px; color: #7fd4ff;
    border: 1px solid rgba(127,212,255,.5); border-radius: 4px; padding: 2px 10px; margin-bottom: 8px;
  }
  #demo-caption .cap-line { font-size: 22px; line-height: 1.5; font-weight: 600; }
  #demo-caption .cap-sub { margin-top: 6px; font-size: 15px; color: #9fb4d4; }
  #demo-title {
    position: fixed; inset: 0; z-index: 10000; display: flex; flex-direction: column;
    align-items: center; justify-content: center; background: radial-gradient(circle at 50% 40%, #12233d, #070c16 70%);
    color: #eaf3ff; font-family: "Microsoft YaHei", "PingFang SC", sans-serif; text-align: center;
  }
  #demo-title h1 { font-size: 54px; margin: 0 0 14px; letter-spacing: 2px; }
  #demo-title p { font-size: 22px; color: #9fc6ee; margin: 6px 0; }
  #demo-title .tag { margin-top: 26px; font-size: 17px; color: #7fd4ff; border: 1px solid rgba(127,212,255,.45);
    border-radius: 30px; padding: 8px 22px; }
`;

const escapeHtml = (s) => String(s || '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

async function main() {
  if (!fs.existsSync(EDGE)) {
    console.error('未找到 Edge：' + EDGE + ' —— 可用 EDGE_PATH 指定浏览器路径');
    process.exit(2);
  }
  fs.mkdirSync(VIDEO_DIR, { recursive: true });

  const browser = await chromium.launch({ executablePath: EDGE, headless: true });
  const context = await browser.newContext({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
    recordVideo: { dir: VIDEO_DIR, size: { width: 1600, height: 900 } },
    locale: 'zh-CN',
  });
  const page = await context.newPage();
  page.on('pageerror', () => {});

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.addStyleTag({ content: CAPTION_CSS });

  // ---- 片头 ----
  await page.evaluate(() => {
    const d = document.createElement('div');
    d.id = 'demo-title';
    d.innerHTML = '<h1>安巡 · 实验室安全应急处置 Agent</h1>' +
      '<p>基于 Agnes Harness（AGH）· 真实大模型自主决策 · 处置闭环可追溯</p>' +
      '<div class="tag">可燃气体泄漏应急演练 · 参赛编号 U126</div>';
    document.body.appendChild(d);
  });
  await page.waitForTimeout(5000);
  await page.evaluate(() => { const d = document.getElementById('demo-title'); if (d) d.remove(); });

  // ---- 字幕条 ----
  await page.evaluate(() => {
    const d = document.createElement('div');
    d.id = 'demo-caption';
    d.innerHTML = '<div class="cap-phase">P0 监测</div><div class="cap-line">实验室正常运行，等待探测器报警…</div><div class="cap-sub"></div>';
    document.body.appendChild(d);
  });

  const setCaption = (phase, line, sub) => page.evaluate(([p, l, s]) => {
    const box = document.getElementById('demo-caption');
    if (!box) return;
    box.innerHTML = '<div class="cap-phase">' + p + '</div><div class="cap-line">' + l +
      '</div><div class="cap-sub">' + s + '</div>';
  }, [escapeHtml(phase), escapeHtml(line), escapeHtml(sub || '')]);

  // ---- 触发演练 ----
  const started = await page.evaluate(async (mode) => {
    const r = await fetch('/api/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    return r.json();
  }, MODE);
  console.log('演练已启动: ' + JSON.stringify(started));

  // ---- 跟随真实进度更新字幕 ----
  const t0 = Date.now();
  let shownSteps = 0;
  let finalStatus = 'unknown';
  let lastPpm = '—';

  const readingOf = (state) => {
    try {
      const devs = state.devices || {};
      const pick = ['S-01', 'S-02', 'S-03'].map((k) => (devs[k] ? devs[k].state.ppm : null)).filter((v) => v !== null);
      return pick.length ? pick.map((v) => v.toFixed(1)).join(' / ') + ' ppm' : '—';
    } catch (e) { return '—'; }
  };

  while ((Date.now() - t0) / 1000 < MAX_SEC) {
    const state = await page.evaluate(async () => (await fetch('/api/state').then((r) => r.json())));
    const run = state.run || {};
    lastPpm = readingOf(state);
    const steps = (run.trace && run.trace.steps) || [];

    if (steps.length > shownSteps) {
      const s = steps[steps.length - 1];
      shownSteps = steps.length;
      const label = (s.tool || '').replace(/_/g, ' ');
      await setCaption(
        '#' + String(s.index).padStart(2, '0') + ' · ' + (s.phase || ''),
        (s.thought || label).slice(0, 90),
        '调用工具 ' + label + '　|　探测器 ' + lastPpm
      );
    } else if (steps.length === 0) {
      await setCaption('P0 监测', '浓度爬升中，等待探测器达到报警阈值…', '探测器 ' + lastPpm);
    }

    if (run.status === 'completed' || run.status === 'aborted' || run.status === 'max_steps_reached') {
      finalStatus = run.status;
      break;
    }
    await page.waitForTimeout(800);
  }

  // ---- 结尾 ----
  await setCaption(
    finalStatus === 'completed' ? '处置闭环' : '演练结束（' + finalStatus + '）',
    finalStatus === 'completed'
      ? '浓度降至安全阈值以下，事故报告已自动生成，全过程可追溯到每一步 Trace。'
      : '本次演练提前结束，可在 mock 模式下重录。',
    '探测器 ' + lastPpm + '　|　共 ' + shownSteps + ' 步'
  );
  await page.waitForTimeout(7000);

  await context.close();
  await browser.close();

  // ---- 重命名输出 ----
  const files = fs.readdirSync(VIDEO_DIR).filter((f) => f.endsWith('.webm'))
    .map((f) => ({ f, t: fs.statSync(path.join(VIDEO_DIR, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  if (!files.length) {
    console.error('未生成视频文件');
    process.exit(3);
  }
  const out = path.join(VIDEO_DIR, '演示视频-安巡-实验室安全应急处置.webm');
  fs.copyFileSync(path.join(VIDEO_DIR, files[0].f), out);
  fs.unlinkSync(path.join(VIDEO_DIR, files[0].f));
  const kb = (fs.statSync(out).size / 1024).toFixed(0);
  console.log('录制完成: %s（%s KB，%d 步，状态 %s）', out, kb, shownSteps, finalStatus);
}

main().catch((e) => { console.error('录制失败: ' + e.message); process.exit(1); });
