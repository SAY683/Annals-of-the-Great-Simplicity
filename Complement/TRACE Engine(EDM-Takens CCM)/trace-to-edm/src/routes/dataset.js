module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.get('/api/inputs', async (_req, res) => {
  try {
    const script = `
import sys, json; sys.path.insert(0, '.')
from pathlib import Path
from project_manager import get_project_manager, PROJECT_ROOT
pm = get_project_manager()
roots = [PROJECT_ROOT / 'data' / 'inputs', pm.current_dir / 'inputs']
files = []
for r in roots:
    if r.exists():
        for f in sorted(r.glob('*.csv')):
            rel = f.relative_to(PROJECT_ROOT)
            files.append({"path": str(rel).replace('\\\\','/'), "name": f.name, "size": f.stat().st_size})
print(json.dumps({"files": files}, ensure_ascii=False))
    `.trim();
    const { out } = await pyScript(script, 5000);
    try { res.json(JSON.parse(out)); }
    catch { res.json({ files: [] }); }
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.get('/api/dataset', async (_req, res) => {
  try {
    const script = `import sys, json; sys.path.insert(0, '.'); from project_manager import get_project_manager; from dataset_manager import DatasetManager; pm = get_project_manager(); dm = DatasetManager(pm.current_dir); print(json.dumps({"entries": dm.entries, "summary": dm.summary()}, ensure_ascii=False, default=str))`;
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000 });
    let out = ''; proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { res.json(JSON.parse(out)); } catch { res.json({ error: out }); } });
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/add', async (req, res) => {
  try {
    const { uuids } = req.body;
    if (!uuids || !uuids.length) return res.status(400).json({ error: 'uuids required' });
    const entries = uuids.map(u => ({ uuid: u, mtime: '', text_preview: '' }));
    const result = await pyDS('add_replay_uuids', [entries]);
    res.json(result);
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/add-text', async (req, res) => {
  try {
    // validateInputPathMiddleware has already resolved and constrained csv_path.
    if (req.resolvedInputPath) {
      const added = await pyDS('add_text_csv', [req.resolvedInputPath]);
      return res.json({ added });
    }
    const rows = Array.isArray(req.body.texts) ? req.body.texts : [];
    if (!rows.length) return res.status(400).json({ error: 'no text rows' });
    const added = await pyDS('add_text_entries', [rows]);
    res.json({ added });
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/remove', async (req, res) => {
  try { await pyDS('remove_entry', [req.body.id]); res.json({ success: true }); }
  catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/clear-processed', async (_req, res) => {
  try { await pyDS('clear_processed'); res.json({ success: true }); }
  catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/reset', async (_req, res) => {
  try { await pyDS('reset_all_pending'); res.json({ success: true }); }
  catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/dataset/update-ts', async (req, res) => {
  try {
    const { id, timestamp } = req.body;
    if (!id || !timestamp) return res.status(400).json({ error: 'id and timestamp required' });
    // Q9 P0-4 修复：原代码字符串拼接 id/timestamp 进 Python 代码，存在注入风险。
    // 改为 JSON 序列化传参，Python 侧用 json.loads 解码（与 pyDS 同模式）。
    const argsJson = JSON.stringify([String(id), String(timestamp)]);
    const script = `
import sys, json; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
_args = json.loads('${argsJson.replace(/'/g, "\\'")}')
_target_id, _target_ts = _args
for e in dm.entries:
    if e['id'] == _target_id:
        e['timestamp'] = _target_ts
        dm._save()
        print('{"success":true}')
        break
else:
    print('{"success":false,"error":"entry not found"}')
    `.trim();
    const { out } = await pyScript(script, 5000);
    try { res.json(JSON.parse(out)); } catch { res.json({ success: true }); }
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

};
