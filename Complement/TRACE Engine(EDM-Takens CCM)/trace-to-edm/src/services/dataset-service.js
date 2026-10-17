const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { ROOT, PYTHON_CMD } = require('../config');

function pyDS(action, args) {
  // 元审计 P1 修缮: Python 注入防护加固
  // 之前对字符串参数仅做 replace(/'/g, "\\'")，遇到 \\ 等转义序列仍可能注入
  // 现统一用 JSON 序列化传递所有参数，Python 侧用 json.loads 解码
  // action 限定为 DatasetManager 的方法名（白名单校验）
  const ALLOWED_ACTIONS = new Set([
    'add_replay_uuids', 'add_text_entries', 'remove_entry', 'clear_processed',
    'reset_all_pending', 'entries', 'summary', 'export_replay_csv', 'export_text_csv',
  ]);
  if (!ALLOWED_ACTIONS.has(action)) {
    return Promise.reject(new Error(`invalid action: ${action}`));
  }

  const argsJson = JSON.stringify(args || []);
  const script = `import sys, json; sys.path.insert(0, '.'); from project_manager import get_project_manager; from dataset_manager import DatasetManager; pm = get_project_manager(); dm = DatasetManager(pm.current_dir); _args = json.loads('${argsJson.replace(/'/g, "\\'")}'); result = dm.${action}(*_args); print(json.dumps(result if not isinstance(result, (list,dict)) else result, ensure_ascii=False, default=str))`;
  return new Promise((resolve, reject) => {
    const proc = spawn(PYTHON_CMD, ['-c', script], { cwd: ROOT, env: { ...process.env, PYTHONIOENCODING: 'utf-8' }, timeout: 15000 });
    let out = ''; proc.stdout.on('data', d => out += d.toString());
    proc.on('close', () => { try { resolve(JSON.parse(out)); } catch { resolve({ raw: out }); } });
    proc.on('error', e => reject(e));
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
