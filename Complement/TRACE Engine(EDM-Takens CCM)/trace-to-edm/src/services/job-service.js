const crypto = require('crypto');
const { spawn } = require('child_process');
const { ROOT, BRIDGE_SCRIPT, PYTHON_CMD } = require('../config');

const activeJobs = new Map();   // jobId -> { process, mode, startTime, logs[] }
const jobHistory = [];          // recent completed jobs

function createJobId() {
  return `job_${Date.now()}_${crypto.randomBytes(3).toString('hex')}`;
}

function emitSSE(res, event, data) {
  // 将事件类型嵌入 data 中, 前端可通过 data._event 读取
  // 服务端 retry: 告知浏览器/代理在连接断开后 30s 内尝试重连
  res.write(`event: ${event}\nretry: 30000\ndata: ${JSON.stringify({ _event: event, ...data })}\n\n`);
}


function streamBridgeProcess(res, args, label) {
  return new Promise((resolve) => {
    emitSSE(res, 'progress', { message: `▶ ${label}` });
    const proc = spawn(PYTHON_CMD, [BRIDGE_SCRIPT, ...args, '--verbose'], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    let sawTraceFailure = false;  // P2：识别 bridge.py 内部的 ✖ TRACE 失败标记

    proc.stdout.on('data', data => {
      const text = data.toString();
      text.split('\n').filter(l => l.trim()).forEach(line => {
        const trimmed = line.trim();
        // P2 修缮：✖ 标记的 TRACE 失败升级为 error 事件，让前端能感知"全 0 行"的真正原因
        if (trimmed.includes('✖ TRACE') || trimmed.includes('✖ L1 提取失败') || trimmed.includes('TRACE 分析失败')) {
          sawTraceFailure = true;
          emitSSE(res, 'error', { message: trimmed });
        } else if (trimmed.includes('✓') || trimmed.includes('完成')) {
          emitSSE(res, 'progress', { message: trimmed });
        } else if (trimmed.includes('⚠') || trimmed.includes('❌')) {
          emitSSE(res, 'warn', { message: trimmed });
        } else if (trimmed) {
          emitSSE(res, 'log', { message: trimmed });
        }
      });
    });

    proc.stderr.on('data', data => {
      const text = data.toString().trim();
      if (text && !text.includes('Loading weights')) emitSSE(res, 'log', { message: text });
    });

    proc.on('close', code => {
      // P2：即使 exit=0，只要有 TRACE 失败标记就返回 'partial'，让 /api/pipeline/run 报告部分失败
      if (code === 0 && sawTraceFailure) {
        emitSSE(res, 'warn', { message: '管线完成但部分 TRACE 分析失败（轨迹 CSV 中 L1 字段可能为 0，trace_status=FAILED 已标记）' });
        resolve('partial');
      } else if (code === 0) {
        resolve('ok');
      } else {
        resolve('failed');
      }
    });
    proc.on('error', err => { emitSSE(res, 'error', { message: err.message }); resolve('failed'); });
  });
}



module.exports = { activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess };
