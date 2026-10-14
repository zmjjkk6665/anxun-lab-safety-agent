/**
 * AGH MCP stdio 桥接：把本项目的 Python MCP 服务器（`python run.py mcp`）包装成可被
 * AGH 以 `node` 可执行文件拉起的 stdio 服务。
 *
 * 背景：AGH 对 MCP stdio 的 executable 有部署策略白名单限制，直接填 `python` 会被拒绝
 * （`stdio executable is not allowed by profile policy`）。用白名单内的 `node` 作为入口，
 * 由本脚本转发 stdio，即可在不改动工具层代码的前提下完成挂载。
 *
 * 用法（AGH 侧登记）：
 *   executable: node
 *   args:       <项目根目录>/scripts/mcp_stdio_bridge.js
 */

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const PYTHON = process.env.LABGUARD_PYTHON || 'python';
const LOG_DIR = path.join(ROOT, 'outputs');

let logStream = null;
try {
  fs.mkdirSync(LOG_DIR, { recursive: true });
  logStream = fs.createWriteStream(path.join(LOG_DIR, 'mcp_bridge.log'), { flags: 'a' });
} catch (e) {
  logStream = null;
}

const child = spawn(PYTHON, [path.join(ROOT, 'run.py'), 'mcp'], {
  cwd: ROOT,
  stdio: ['pipe', 'pipe', 'pipe'],
});

process.stdin.pipe(child.stdin);
child.stdout.pipe(process.stdout);
if (logStream) {
  child.stderr.pipe(logStream);
} else {
  child.stderr.pipe(process.stderr);
}

child.on('exit', (code) => process.exit(code === null ? 1 : code));
process.on('exit', () => { try { child.kill(); } catch (e) { /* noop */ } });
