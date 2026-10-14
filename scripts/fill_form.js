/**
 * 赛事提交表单自动填写脚本（https://agnes-ai.cn/hackathon → 作品提交）。
 *
 * 用法：
 *   node scripts/fill_form.js --dump                                  # 只打印表单字段结构
 *   node scripts/fill_form.js --dry  --phone <手机号> --email <邮箱>   # 填写 + 上传 + 截图，不点提交
 *   node scripts/fill_form.js --submit --phone <手机号> --email <邮箱> # 填写 + 上传 + 提交 + 结果截图
 *
 * 说明：表单无需登录，仅需队伍名称/队长姓名/手机号/邮箱与报名信息一致；
 *      脚本不接收、不存储任何密钥，仅注入上述字段与本地文案/文件。
 */

const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'outputs', 'form');
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const arg = (name, dflt) => {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] && !process.argv[i + 1].startsWith('--') ? process.argv[i + 1] : dflt;
};

const VALUES = () => ({
  team: arg('--team', '大肥鱼脚香香'),
  leader: arg('--leader', '李家杰'),
  phone: arg('--phone', ''),
  email: arg('--email', ''),
  title: arg('--title', '安巡 · 实验室安全应急处置 Agent'),
  intro: '安巡：基于AGH的实验室泄漏应急Agent，多源交叉确认、机械臂兜底关阀，闭环处置并出具报告。',
  detail: fs.readFileSync(path.join(ROOT, 'docs', '作品详情-提交版.md'), 'utf-8').trim(),
  // 单行 input（max 500），换行会被丢弃；且前端校验要求以 http(s):// 开头，因此只能放纯 URL，用 ｜ 分隔
  links: [
    'https://github.com/zmjjkk6665/anxun-lab-safety-agent',
    'http://127.0.0.1:8787',
    'https://github.com/zmjjkk6665/anxun-lab-safety-agent/blob/main/media/演示视频-安巡-实验室安全应急处置.mp4',
    'https://raw.githubusercontent.com/zmjjkk6665/anxun-lab-safety-agent/main/media/演示视频-安巡-实验室安全应急处置.mp4',
  ].join(' ｜ '),
  zip: path.join(ROOT, 'dist', '本科生组-U126-大肥鱼脚香香-李家杰.zip'),
});

/** 给表单控件打上序号标记，便于按下标精确注入（React 受控组件用 fill 触发 input 事件）。 */
async function markFields(page) {
  return page.evaluate(() => {
    const visible = (e) => !!(e.offsetParent || e.type === 'file');
    const els = Array.from(document.querySelectorAll('input, textarea')).filter(visible);
    els.forEach((e, i) => e.setAttribute('data-fill-idx', String(i)));
    return els.map((e, i) => ({
      i,
      tag: e.tagName,
      type: e.type || '',
      placeholder: e.placeholder || '',
      value: (e.type === 'file' ? '' : e.value || '').slice(0, 20),
      maxLength: e.maxLength > 0 ? e.maxLength : null,
    }));
  });
}

(async () => {
  const mode = process.argv.includes('--submit') ? 'submit' : (process.argv.includes('--dump') ? 'dump' : 'dry');
  const v = VALUES();
  fs.mkdirSync(OUT, { recursive: true });

  if (mode !== 'dump') {
    if (!v.phone || !v.email) throw new Error('缺少 --phone / --email');
    if (!fs.existsSync(v.zip)) throw new Error('未找到 ZIP: ' + v.zip);
  }

  const browser = await chromium.launch({ executablePath: EDGE, headless: mode !== 'dump' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', () => {});

  await page.goto('https://agnes-ai.cn/hackathon', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await wait(9000);

  // 页面有吸顶导航遮挡，Playwright 的常规点击会被拦截，改用 DOM 原生 click 触发 React 事件
  const clicked = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll('button, a'))
      .find((b) => (b.innerText || '').trim() === '作品提交');
    if (!btn) return false;
    btn.scrollIntoView({ block: 'center' });
    btn.click();
    return true;
  });
  console.log('触发提交入口:', clicked);
  await wait(3000);
  const opened = await page.evaluate(() => /队伍名称|作品简介/.test(document.body.innerText));
  console.log('弹窗已打开:', opened);

  let fields = await markFields(page);
  console.log('=== 表单字段 ===');
  fields.forEach((f) => console.log(`#${f.i} ${f.tag} type=${f.type} max=${f.maxLength} ph=${f.placeholder}`));

  if (mode === 'dump') {
    await page.screenshot({ path: path.join(OUT, 'form-empty.png') });
    console.log('已截图 outputs/form/form-empty.png');
    await wait(8000);
    await browser.close();
    return;
  }

  // 字段顺序（与表单视觉顺序一致）：队伍名称 / 队长姓名 / 手机号 / 邮箱 / 作品名称 / 简介 / 详情 / 文件 / 链接
  const textInputs = fields.filter((f) => f.type !== 'file' && f.tag === 'INPUT');
  const textareas = fields.filter((f) => f.tag === 'TEXTAREA');
  const fileIdx = (fields.find((f) => f.type === 'file') || {}).i;

  const setVal = async (idx, text, label) => {
    const loc = page.locator(`[data-fill-idx="${idx}"]`);
    await loc.click({ timeout: 8000 }).catch(() => {});
    await loc.fill('');
    await loc.fill(text);
    const got = await loc.inputValue();
    console.log(`填写 ${label}: ${got.length} 字${got === text ? ' ✓' : ' ✗ 内容不一致'}`);
  };

  const plan = [
    [textInputs[0], v.team, '队伍名称'],
    [textInputs[1], v.leader, '队长姓名'],
    [textInputs[2], v.phone, '手机号'],
    [textInputs[3], v.email, '邮箱'],
    [textInputs[4], v.title, '作品名称'],
    [textareas[0], v.intro, '作品简介'],
    [textareas[1], v.detail, '作品详情'],
    [textareas[2] || textInputs[5], v.links, '作品链接'],
  ];
  for (const [f, text, label] of plan) {
    if (!f) { console.log(`⚠ 未找到字段: ${label}`); continue; }
    await setVal(f.i, text, label);
  }

  if (fileIdx !== undefined) {
    await page.locator(`[data-fill-idx="${fileIdx}"]`).setInputFiles(v.zip);
    await wait(4000);
    console.log('已上传 ZIP:', path.basename(v.zip), (fs.statSync(v.zip).size / 1024 / 1024).toFixed(2) + ' MB');
  } else {
    console.log('⚠ 未找到文件上传控件');
  }

  // 回读前端校验提示，避免带着报错提交
  const errors = await page.evaluate(() => {
    const pat = /(需以|不能为空|必填|格式|请输入正确的)/;
    return document.body.innerText.split('\n').map((s) => s.trim()).filter((s) => pat.test(s));
  });
  console.log('校验提示:', errors.length ? errors.join(' / ') : '无');

  const shot = path.join(OUT, mode === 'submit' ? 'form-before-submit.png' : 'form-filled-dry.png');
  await page.screenshot({ path: shot, fullPage: false });
  console.log('已截图', path.relative(ROOT, shot));

  if (mode === 'submit') {
    await page.locator('button:has-text("提交作品")').last().click({ timeout: 15000 });
    await wait(6000);
    const text = await page.evaluate(() => document.body.innerText);
    fs.writeFileSync(path.join(OUT, 'submit-result.txt'), text, 'utf-8');
    await page.screenshot({ path: path.join(OUT, 'form-after-submit.png'), fullPage: false });
    const hint = text.split('\n').filter((l) => /成功|已提交|失败|错误|请|锁/.test(l)).slice(0, 8).join(' / ');
    console.log('提交后提示:', hint || '(未捕获提示，见 submit-result.txt)');
  }

  await wait(6000);
  await browser.close();
})().catch((e) => {
  console.log('ERR', e.message.slice(0, 300));
  process.exit(1);
});
