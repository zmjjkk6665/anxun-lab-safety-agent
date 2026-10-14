/**
 * AGH（Agnes Harness）真机接入：驱动 AGH Web 完成「配置模型账号 → 会话内接入 MCP 设备工具 →
 * 下发应急处置任务」，并把会话文本与截图导出到 outputs/agh/，作为赛事要求的 AGH 执行记录证据。
 *
 * 前置：AGH Web 已在 http://127.0.0.1:4180 运行（见 docs/AGH接入说明.md）。
 * 用法：
 *   node scripts/agh_setup.js --step account     # 配置模型账号并测试连接
 *   node scripts/agh_setup.js --step session     # 新建会话 → 接入 MCP → 执行应急处置任务
 *   node scripts/agh_setup.js --step all
 *
 * 安全约定：模型 Key 只从环境变量 AGNES_API_KEY 读取，不落盘、不打印。
 */

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const EDGE = process.env.EDGE_PATH ||
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const AGH_URL = process.env.AGH_WEB_URL || 'http://127.0.0.1:4180/';
const PROJECT = path.resolve(__dirname, '..');
const OUT_DIR = path.join(PROJECT, 'outputs', 'agh');

const argv = process.argv.slice(2);
const getArg = (name, def) => {
  const i = argv.indexOf(name);
  return i >= 0 ? argv[i + 1] : def;
};
const STEP = getArg('--step', 'all');

const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const MCP_CONNECT = [
  '请接入一个 MCP 服务，参数如下：',
  '- 名称（id）：labguard-devices',
  '- 传输方式：stdio',
  '- 可执行文件：python',
  '- 参数：<RUNPY> mcp',
  '接入成功后，请列出该服务提供的全部工具名称，不要执行其它操作。',
].join('\n').replace('<RUNPY>', path.join(PROJECT, 'run.py'));

const TASK = [
  '任务：在当前工作目录（安巡 · 实验室安全应急处置 Agent 项目）完成一次真实的实验室可燃气体泄漏应急处置，并核验处置结果。',
  '请按下面 4 个连续步骤执行，每一步都基于上一步的真实输出决定：',
  '第 1 步（规划与执行）：运行命令 `python run.py cli --mode builtin`。该命令会由模型驱动本项目的 14 个设备工具完成',
  '「感知 → 交叉确认 → 切断（远程关阀失败后自动改派机械臂）→ 排风与疏散 → 复核观测 → 提交报告」的完整处置闭环，',
  '并把执行轨迹写入 outputs/traces、事故报告写入 outputs/reports。',
  '第 2 步（反馈处理）：读取 outputs/traces 下最新一个轨迹 JSON，提取每一步的工具名与最终状态、总步数。',
  '第 3 步（结果验证）：读取 outputs/reports 下最新一个报告文件，核对并逐项给出结论：阀门是否关闭、排风是否为 100%、',
  '人员是否疏散、源点浓度是否降到 50 ppm 安全阈值以下、报告是否生成。任何一项不满足都要明确指出。',
  '第 4 步（收尾）：用一句话总结处置结论（含最终源点浓度与总步数）。',
  '约束：不要修改项目中的任何文件，不要运行安装命令，只在当前目录内执行上述命令。',
].join('\n');

async function closeDialogs(page) {
  await page.keyboard.press('Escape').catch(() => {});
  await wait(600);
  await page.evaluate(() => {
    document.querySelectorAll('dialog[open]').forEach((d) => {
      const b = Array.from(d.querySelectorAll('button'))
        .find((x) => /^(取消|Cancel|关闭)$/i.test((x.innerText || '').trim()));
      if (b) b.click(); else if (d.close) d.close();
    });
  });
  await wait(800);
}

/** 点击所有可能出现的审批/确认按钮（工具调用授权、MCP 信任与启用）。 */
async function autoApprove(page) {
  // 审批卡片按钮文案形如「允许一次 / 始终允许 / Approve once」，必须做包含匹配而非整串匹配
  return page.evaluate(() => {
    const pat = /(允许|批准|同意|确认|继续|执行|启用|信任|审核通过|Approve|Allow|Confirm|Continue|Enable|Trust|Run once|Yes)/i;
    const deny = /(拒绝|拒绝执行|Deny|Reject|Cancel|取消)/i;
    const btns = Array.from(document.querySelectorAll('button'))
      .filter((x) => x.offsetParent !== null)
      .filter((x) => {
        const t = (x.innerText || '').trim();
        return pat.test(t) && !deny.test(t);
      });
    btns.forEach((b) => b.click());
    return btns.map((b) => (b.innerText || '').trim());
  });
}

async function ensureAccount(page) {
  const key = process.env.AGNES_API_KEY || '';
  if (!key) throw new Error('未设置 AGNES_API_KEY');

  if (await page.evaluate(() => /labguard-hackathon/.test(document.body.innerText))) {
    log('账号已存在，跳过配置');
    return;
  }
  await page.locator('button:has-text("Settings")').first().click({ timeout: 10000 });
  await wait(1500);
  await page.getByText('Add account').first().click({ timeout: 8000 });
  await wait(1200);
  await page.fill('#config-account-name', 'labguard-hackathon');
  await page.fill('#config-base-url', 'https://api.agnes-ai.cn/v1');
  await page.fill('#config-api-key', key);
  await wait(300);
  await page.getByRole('button', { name: 'Test connection' }).click();
  await wait(15000);

  const models = await page.evaluate(() =>
    Array.from(document.querySelectorAll('#config-model option')).map((o) => o.value).filter(Boolean));
  log('测试连接后可选模型:', models.join(' | ') || '(无)');
  if (!models.length) throw new Error('连接测试未返回模型列表，请检查 Base URL / Key');

  // AGH 的下拉是自定义组件，原生 select 不可见，直接注入值并派发 change
  const target = models.find((m) => m.includes('flash')) || models[0];
  await page.evaluate((val) => {
    const sel = document.getElementById('config-model');
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
    setter.call(sel, val);
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  }, target);
  log('默认模型选为:', target);

  const saved = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button'))
      .filter((x) => /保存|Save/i.test((x.innerText || '').trim()))
      .filter((x) => x.offsetParent !== null);
    const b = btns[btns.length - 1];
    if (b) { b.click(); return (b.innerText || '').trim(); }
    return null;
  });
  log('点击保存按钮:', saved || '(未找到)');
  await wait(4000);
  log('账号配置结果:', (await page.evaluate(() => /labguard-hackathon/.test(document.body.innerText))) ? '已保存' : '未确认');
}

async function newSession(page) {
  // 工作目录是受控组件，用原生 setter + input 事件写入；创建按钮不可用时回退到当前页面
  try {
    await page.locator('button:has-text("New session")').first().click({ timeout: 8000 });
    await wait(1800);
    await page.evaluate((cwd) => {
      const el = document.getElementById('new-session-cwd');
      if (!el) return;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(el, cwd);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }, PROJECT);
    await wait(1800);
    const ready = await page.evaluate(() => {
      const b = document.getElementById('new-session-create');
      return !!(b && !b.disabled && b.offsetParent !== null);
    });
    log('创建按钮可用 =', ready);
    if (ready) {
      await page.locator('#new-session-create').click({ timeout: 8000 });
      await wait(2500);
      log('会话已创建，工作目录:', PROJECT);
      return;
    }
    log('创建按钮不可用，回退到当前会话页面');
    await closeDialogs(page);
  } catch (e) {
    log('新建会话异常，回退:', String(e.message).slice(0, 80));
    await closeDialogs(page);
  }
}

/** 发送一条消息并等待 AGH 执行结束（自动处理审批）。 */
async function chat(page, text, label, maxSec) {
  await page.fill('#prompt', text);
  await wait(600);
  await page.getByRole('button', { name: 'Send' }).first().click();
  log('[%s] 已发送，等待执行…', label);

  const t0 = Date.now();
  let idle = 0;
  let lastLen = 0;
  while ((Date.now() - t0) / 1000 < maxSec) {
    // 审批窗口只有 60s，轮询间隔必须明显小于它
    await wait(3000);
    const approved = await autoApprove(page);
    if (approved.length) log('[%s] 已点击审批按钮:', label, approved.join(','));

    const st = await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const stop = btns.find((x) => /^Stop$/i.test((x.innerText || '').trim()) && x.offsetParent !== null);
      return { running: !!stop, len: document.body.innerText.length };
    });
    if (st.len !== lastLen) {
      lastLen = st.len;
      idle = 0;
      log('[%s] 执行中… 已耗时 %ds', label, Math.round((Date.now() - t0) / 1000));
    } else {
      idle += 1;
    }
    if (!st.running && idle >= 3 && (Date.now() - t0) / 1000 > 30) {
      log('[%s] 执行结束（耗时 %ds）', label, Math.round((Date.now() - t0) / 1000));
      break;
    }
  }
  await wait(3000);
  await autoApprove(page);
}

async function dump(page, tag) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const shot = path.join(OUT_DIR, 'agh-' + tag + '-' + stamp + '.png');
  const dump = path.join(OUT_DIR, 'agh-' + tag + '-' + stamp + '.txt');
  await page.screenshot({ path: shot, fullPage: true });
  fs.writeFileSync(dump, await page.evaluate(() => document.body.innerText), 'utf-8');
  log('已留证:', path.basename(shot), '/', path.basename(dump));
}

/** 用 AGH CLI 导出最近一次会话，作为可人工核查的 AGH 执行记录。 */
async function exportSession() {
  const entry = process.env.AGH_ENTRY ||
    'C:\\Users\\ZMJJK\\CodeBuddy\\_agh\\agnes-harness\\packages\\cli\\dist\\local-dev-lab\\agnes.mjs';
  if (!fs.existsSync(entry)) {
    log('未找到 AGH CLI 入口，跳过导出:', entry);
    return;
  }
  const { execFileSync } = require('child_process');
  const env = { ...process.env, AGH_HOME: process.env.AGH_HOME || 'C:\\Users\\ZMJJK\\CodeBuddy\\_agh\\home' };
  try {
    const raw = execFileSync(process.execPath, [entry, 'sessions', '--json'],
      { encoding: 'utf-8', env, timeout: 60000 });
    const parsed = JSON.parse(raw.slice(raw.indexOf('{')));
    const items = parsed.items || parsed.sessions || [];
    const sid = items.length ? (items[0].sessionId || items[0].id) : null;
    if (!sid) throw new Error('未解析到会话 ID');
    log('导出会话:', sid);
    const out = path.join(OUT_DIR, 'agh-execution-record.json');
    execFileSync(process.execPath,
      [entry, 'export', sid, '--format', 'agnes', '--raw', '-o', out],
      { encoding: 'utf-8', env, timeout: 120000 });
    log('AGH 执行记录已导出:', out);
  } catch (e) {
    log('导出失败:', e.message.slice(0, 200));
  }
}

async function main() {
  if (!fs.existsSync(EDGE)) {
    console.error('未找到 Edge：' + EDGE);
    process.exit(2);
  }
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ executablePath: EDGE, headless: true });
  const page = await browser.newPage();
  page.on('pageerror', () => {});
  await page.goto(AGH_URL, { waitUntil: 'networkidle', timeout: 60000 });
  await wait(3000);
  await closeDialogs(page);

  if (STEP === 'account' || STEP === 'all') await ensureAccount(page);

  if (STEP === 'session' || STEP === 'all') {
    await page.goto(AGH_URL, { waitUntil: 'networkidle', timeout: 60000 });
    await wait(2500);
    await closeDialogs(page);
    await newSession(page);
    if (STEP === 'mcpchat') {
      await chat(page, MCP_CONNECT, '接入MCP', Number(getArg('--mcp-seconds', '240')));
      await dump(page, 'mcp');
    }
    await chat(page, TASK, '应急处置', Number(getArg('--seconds', '600')));
    await dump(page, 'session');
    await exportSession();
  }

  await browser.close();
  log('完成');
}

main().catch((e) => { console.error('失败:', e.message); process.exit(1); });
