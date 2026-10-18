const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { ROOT, PYTHON_CMD } = require('../config');

function pyDS(action, args) {
  // Pass JSON over stdin instead of embedding it in the Python command line.
  // This avoids Windows command-line length limits and quoting/injection risks.
  const ALLOWED_ACTIONS = new Set([
    'add_replay_uuids', 'add_text_entries', 'add_text_csv', 'remove_entry',
    'clear_processed', 'reset_all_pending', 'entries', 'summary',
    'export_replay_csv', 'export_text_csv',
  ]);
  if (!ALLOWED_ACTIONS.has(action)) {
    return Promise.reject(new Error(`invalid action: ${action}`));
  }

  const script = `
import sys, json
sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager

payload = json.load(sys.stdin)
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
result = getattr(dm, payload["action"])(*payload["args"])
print(json.dumps(result, ensure_ascii=False, default=str))
  `.trim();

  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], {
      cwd: ROOT,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      timeout: 15000,
    });
    let out = '';
    let err = '';
    proc.stdout.on('data', chunk => { out += chunk.toString(); });
    proc.stderr.on('data', chunk => { err += chunk.toString(); });
    proc.on('close', code => {
      if (code !== 0) {
        reject(new Error(err.trim() || `dataset manager exited with code ${code}`));
        return;
      }
      try {
        resolve(JSON.parse(out));
      } catch {
        reject(new Error(`dataset manager returned invalid JSON: ${out.slice(0, 500)}`));
      }
    });
    proc.on('error', reject);
    proc.stdin.write(JSON.stringify({ action, args: args || [] }));
    proc.stdin.end();
  });
}


function getDatasetExports() {
  const script = `
import sys, json; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
pending = dm.pending
if not pending:
    print(json.dumps({"error":"no pending entries"}))
    sys.exit(0)
replay_csv = dm.export_replay_csv()
text_csv = dm.export_text_csv()
print(json.dumps({
    "replay_csv": str(replay_csv) if (replay_csv.exists() and len([e for e in pending if e['type']=='replay'])>0) else None,
    "text_csv": str(text_csv) if (text_csv.exists() and len([e for e in pending if e['type']=='text'])>0) else None,
    "pending_replay": len([e for e in pending if e['type']=='replay']),
    "pending_text": len([e for e in pending if e['type']=='text']),
    "pending_ids": [e['id'] for e in pending],
}, ensure_ascii=False))
  `.trim();
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 15000 });
    let out = '';
    proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { resolve(JSON.parse(out)); } catch { resolve({ error: out }); } });
    proc.on('error', e => reject(e));
  });
}

function markDatasetProcessed(ids) {
  // 使用临时文件传递 IDs (避免特殊字符破坏 Python 字符串)
  const tmpFile = path.join(ROOT, 'data', 'outputs', `_mark_ids_${Date.now()}.json`);
  fs.writeFileSync(tmpFile, JSON.stringify(ids));
  const script = `
import sys, json, os; sys.path.insert(0, '.')
from project_manager import get_project_manager
from dataset_manager import DatasetManager
pm = get_project_manager()
dm = DatasetManager(pm.current_dir)
with open('${tmpFile.replace(/\\/g, '\\\\')}', 'r', encoding='utf-8') as f:
    ids = json.load(f)
errors = []
for eid in ids:
    try: dm.mark_processed(eid)
    except Exception as e: errors.append(str(e))
pm.update_row_count()
rows = 0
if os.path.exists(pm.current_csv):
    with open(pm.current_csv, 'r', encoding='utf-8') as f:
        rows = sum(1 for _ in f) - 1
os.remove('${tmpFile.replace(/\\/g, '\\\\')}')
print(json.dumps({"rows": rows, "edm_ready": rows >= 15}, ensure_ascii=False))
  `.trim();
  return new Promise((resolve) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 10000 });
    let out = '';
    proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { resolve(JSON.parse(out)); } catch { resolve({}); } });
    proc.on('error', () => resolve({}));
  });
}


module.exports = { pyDS, getDatasetExports, markDatasetProcessed };
