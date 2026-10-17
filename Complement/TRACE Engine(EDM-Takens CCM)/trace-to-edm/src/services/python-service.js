const { spawn } = require('child_process');
const { ROOT, BRIDGE_SCRIPT, PYTHON_CMD } = require('../config');

function pyCall(args, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, [BRIDGE_SCRIPT, ...args], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let out = '', err = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('timeout')); }, timeout);
    proc.stdout.on('data', d => out += d.toString());
    proc.stderr.on('data', d => err += d.toString());
    proc.on('close', code => {
      clearTimeout(timer);
      const trimmedOut = out.trim();
      const trimmedErr = err.trim();
      // 尝试 JSON 解析
      if (trimmedOut) {
        try {
          const parsed = JSON.parse(trimmedOut);
          // 若 Python 输出了显式 success 字段，尊重该字段
          if (parsed && typeof parsed === 'object' && 'success' in parsed) {
            resolve(parsed);
            return;
          }
          // 数组是合法的无 success 字段输出（如 --list-projects 输出项目数组），
          // 原样返回，避免被 {...parsed} 展开为 {0: {...}, 1: {...}} 的畸形对象。
          // 回归修复 (debt-12.14): 上次 pyCall 修缮未覆盖数组输出路径，
          // 导致 /api/projects 下拉为空（前端 Array.isArray 检查失败）。
          if (Array.isArray(parsed)) {
            resolve(parsed);
            return;
          }
          // JSON 解析成功但无 success 字段: 仅当 exit code=0 且无 stderr 时才视为成功
          resolve({
            success: code === 0 && !trimmedErr,
            ...parsed,
            _warning: 'JSON 无显式 success 字段，依据 exit code 与 stderr 推断',
            exit_code: code,
            stderr: trimmedErr,
          });
          return;
        } catch (e) {
          // JSON 解析失败，进入下方 fallback
        }
      }
      // Fallback: stdout 不是 JSON。success 必须同时满足 exit code=0 且 stderr 为空。
      // 若 exit code!=0 或 stderr 非空，即使 exit code=0 也视为失败（stderr 表明 Python 报错）。
      resolve({
        success: code === 0 && !trimmedErr && !trimmedOut,
        output: trimmedOut,
        error: trimmedErr || (code !== 0 ? `Python 退出码非零: ${code}` : ''),
        exit_code: code,
      });
    });
    proc.on('error', e => { clearTimeout(timer); reject(e); });
  });
}

// 安全的 Python 脚本执行 (自动超时+错误处理)
function pyScript(script, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], {
      cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });
    let out = '', err = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('timeout')); }, timeout);
    proc.stdout.on('data', d => out += d.toString());
    proc.stderr.on('data', d => err += d.toString());
    proc.on('close', () => { clearTimeout(timer); resolve({ out, err }); });
    proc.on('error', e => { clearTimeout(timer); reject(e); });
  });
}

// ── 运行时状态 ────────────────────────────────────────────

function errorResponse(e, defaultMessage = 'Internal Server Error') {
  console.error('[Server] 路由错误:', e);
  return { error: IS_PROD ? defaultMessage : (e.message || defaultMessage) };
}

// ── Express 初始化 ────────────────────────────────────────

module.exports = { pyCall, pyScript, errorResponse };
