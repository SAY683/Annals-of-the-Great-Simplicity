module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.get('/api/projects', async (_req, res) => {
  // P1-b：服务端 5s 内存缓存
  const cached = getCached('projects');
  if (cached) return res.json(cached);
  try {
    const result = await pyCall(['--list-projects']);
    setCached('projects', result);
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// P0-2/P0-3 (Round 21 §P0-A): 项目名称格式校验
// 防止 path traversal — name 会传给 Python project_manager 拼接路径
// 允许: 字母/数字/下划线/连字符/中文, 长度 1-64, 禁止 ../ \ / : 等路径字符
const PROJECT_NAME_RE = /^[A-Za-z0-9_\-\u4e00-\u9fa5]{1,64}$/;
function isValidProjectName(name) {
  return typeof name === 'string' && PROJECT_NAME_RE.test(name);
}

app.post('/api/projects', async (req, res) => {
  const { name, description } = req.body;
  if (!isValidProjectName(name)) {
    return res.status(400).json({ error: 'name 必须为 1-64 位字母/数字/下划线/连字符/中文', code: 'INVALID_NAME' });
  }
  try {
    const result = await pyCall(['--create-project', name]);
    invalidateCache('projects');  // P1-b：项目列表变更后失效缓存
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.put('/api/projects/activate', async (req, res) => {
  const { name } = req.body;
  if (!isValidProjectName(name)) {
    return res.status(400).json({ error: 'name 必须为 1-64 位字母/数字/下划线/连字符/中文', code: 'INVALID_NAME' });
  }
  try {
    const result = await pyCall(['--project', name]);
    // P1-b：项目切换后失效所有缓存（模型列表也因项目隔离而变化）
    invalidateCache();
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.delete('/api/projects/:name', async (req, res) => {
  const { name } = req.params;
  if (!isValidProjectName(name)) {
    return res.status(400).json({ error: 'name 必须为 1-64 位字母/数字/下划线/连字符/中文', code: 'INVALID_NAME' });
  }
  try {
    const result = await pyCall(['--delete-project', name]);
    invalidateCache('projects');  // P1-b：项目删除后失效缓存
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.get('/api/work-scan', async (_req, res) => {
  try {
    const result = await pyCall(['--scan-work']);
    res.json(result);
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.delete('/api/work-uuid/:uuid', async (req, res) => {
  // 安全校验: 允许标准UUID和非标准短名称(如test-abort)，但拒绝路径遍历和特殊字符
  const SAFE_NAME_RE = /^[A-Za-z0-9_\-]{1,64}$/;
  if (!SAFE_NAME_RE.test(req.params.uuid)) {
    return res.status(400).json({ error: 'INVALID_UUID', detail: 'Only alphanumeric, hyphen, underscore allowed (max 64 chars)' });
  }
  try {
    const script = `
import sys, json; sys.path.insert(0, '.')
from work_scanner import WorkScanner
ws = WorkScanner()
result = ws.delete_uuids(['${req.params.uuid}'], dry_run=False)
print(json.dumps(result, ensure_ascii=False))
    `.trim();
    const proc = spawn(PYTHON_CMD, ['-c', script], {
      cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000,
    });
    let out = '';
    proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { res.json(JSON.parse(out)); } catch { res.json({ raw: out }); } });
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/work-clean', async (req, res) => {
  const dryRun = req.body.dry_run !== false;
  const orphansOnly = req.body.orphans_only === true;
  // P0 修缮：JavaScript 的 true/false 插入 Python 代码必须转为 True/False
  // 否则 Python 会抛 NameError: name 'true' is not defined
  const dryRunPy = dryRun ? 'True' : 'False';
  const orphansOnlyPy = orphansOnly ? 'True' : 'False';
  try {
    const script = `
import sys, json
sys.path.insert(0, '.')
from work_scanner import WorkScanner
ws = WorkScanner()
result = ws.delete_invalid(dry_run=${dryRunPy}) if not ${orphansOnlyPy} else ws.delete_orphans(dry_run=${dryRunPy})
print(json.dumps(result, ensure_ascii=False))
    `.trim();
    const { out, err } = await pyScript(script, 15000);
    if (err && err.trim()) {
      console.warn('[work-clean] Python stderr:', err.trim());
    }
    try { res.json(JSON.parse(out)); } catch { res.json({ raw: out.trim(), error: err.trim() || undefined }); }
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

app.post('/api/replay-uuids', async (req, res) => {
  const { uuids } = req.body;
  if (!uuids || !uuids.length) return res.status(400).json({ error: 'uuids required' });

  const jobId = createJobId();
  const tmpCsv = path.join(ROOT, 'data', 'outputs', `_replay_selected_${jobId}.csv`);
  const uuidsFile = path.join(ROOT, 'data', 'outputs', `_uuids_${jobId}.json`);

  try {
    // 将 UUID 写入临时 JSON 文件 (避免命令行参数注入)
    fs.writeFileSync(uuidsFile, JSON.stringify(uuids));

    const { out, err: setupErr } = await pyScript(`
import sys, json; sys.path.insert(0, '.')
from work_scanner import WorkScanner
from pathlib import Path
ws = WorkScanner()
with open('${uuidsFile.replace(/\\/g, '\\\\')}', 'r', encoding='utf-8') as f:
    uuids = json.load(f)
count = ws.export_replay_csv(uuids, Path('${tmpCsv.replace(/\\/g, '\\\\')}'))
print(json.dumps({"count": count}))
    `.trim(), 15000);

    if (!fs.existsSync(tmpCsv)) {
      return res.status(500).json({ error: 'Failed to create replay CSV', detail: setupErr });
    }

    // 直接 spawn bridge.py (实时 SSE)
    const args = [BRIDGE_SCRIPT, '--replay', tmpCsv, '--verbose'];
    const proc = spawn(PYTHON_CMD, args, { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });

    const job = { id: jobId, mode: 'replay-uuids', startTime: new Date().toISOString(), status: 'running' };
    activeJobs.set(jobId, { ...job, process: proc });

    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
    emitSSE(res, 'start', { job_id: jobId, mode: 'replay-uuids', count: uuids.length });

    proc.stdout.on('data', data => {
      const text = data.toString();
      text.trim().split('\n').filter(l => l.trim()).forEach(line => {
        if (line.includes('✓') || line.includes('完成')) emitSSE(res, 'progress', { message: line.trim() });
        else if (line.includes('⚠') || line.includes('❌')) emitSSE(res, 'warn', { message: line.trim() });
        else emitSSE(res, 'log', { message: line.trim() });
      });
    });

    proc.stderr.on('data', data => { const t = data.toString().trim(); if (t) emitSSE(res, 'log', { message: t }); });

    proc.on('close', code => {
      job.status = code === 0 ? 'completed' : 'failed';
      job.endTime = new Date().toISOString();
      activeJobs.delete(jobId);
      jobHistory.unshift({ id: jobId, status: job.status, mode: job.mode, startTime: job.startTime });
      if (jobHistory.length > 50) jobHistory.pop();
      emitSSE(res, 'done', { job_id: jobId, success: code === 0 });
      res.end();
      try { fs.unlinkSync(tmpCsv); fs.unlinkSync(uuidsFile); } catch {}
    });

    proc.on('error', err => {
      job.status = 'error'; activeJobs.delete(jobId);
      emitSSE(res, 'error', { message: err.message }); res.end();
      try { fs.unlinkSync(tmpCsv); fs.unlinkSync(uuidsFile); } catch {}
    });

  } catch (e) {
    res.status(500).json(errorResponse(e));
    try { fs.unlinkSync(uuidsFile); } catch {}
  }
});

app.get('/api/work-uuid/:uuid/text', async (req, res) => {
  // 安全校验: 与 DELETE /api/work-uuid/:uuid 同一规则，防止路径遍历与命令注入
  const SAFE_NAME_RE = /^[A-Za-z0-9_\-]{1,64}$/;
  if (!SAFE_NAME_RE.test(req.params.uuid)) {
    return res.status(400).json({ error: 'INVALID_UUID', detail: 'Only alphanumeric, hyphen, underscore allowed (max 64 chars)' });
  }
  // P0 修缮: UUID 已通过白名单校验，可安全插值；桥接脚本固定单引号包裹
  const script = `
import sys, json; sys.path.insert(0, '.')
from bridge import _find_input_text
text = _find_input_text('${req.params.uuid}')
print(json.dumps({"text": text or ""}, ensure_ascii=False))
  `.trim();
  try {
    const { out, err } = await pyScript(script, 10000);
    if (err && err.trim()) {
      // bridge.py 在文件读取失败时会向 stderr 写警告，但不影响返回空文本
      console.warn(`[work-uuid/text] Python stderr for ${req.params.uuid}:`, err.trim());
    }
    try {
      const parsed = JSON.parse(out);
      res.json(parsed);
    } catch {
      // stdout 不是合法 JSON — 视为未找到
      res.status(404).json({ error: 'TEXT_NOT_FOUND', raw: out.trim() });
    }
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

};
