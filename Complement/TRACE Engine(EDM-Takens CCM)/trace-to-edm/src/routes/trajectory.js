module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.get('/api/trajectory', (_req, res) => {
  const traj = readTrajectoryCSV();
  res.json(traj);
});

app.post('/api/trajectory/clear', async (_req, res) => {
  try {
    const script = `
import sys; sys.path.insert(0, '.')
from project_manager import get_project_manager
pm = get_project_manager()
csv_path = str(pm.current_csv)
with open(csv_path, 'r', encoding='utf-8') as f:
    header = f.readline()
with open(csv_path, 'w', encoding='utf-8') as f:
    f.write(header)
pm.update_row_count()
print('{"success":true,"rows":0}')
    `.trim();
    const { out } = await pyScript(script, 10000);
    try { res.json(JSON.parse(out)); } catch { res.json({ success: true }); }
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

// ── P2 (§20.12): 一键导出人话版 Markdown 报告 ─────────────────────
// 复用 buildTrajectoryReport(), 生成后返回文件路径与生成时间.
app.get('/api/trajectory/export/md', async (_req, res) => {
  try {
    const report = buildTrajectoryReport();
    reqLog(_req, 'info', `人话版报告已生成: projects/${report.projectName}/reports/latest.md`);
    res.json({
      success: true,
      path: `projects/${report.projectName}/reports/latest.md`,
      project: report.projectName,
      generated: report.generated,
      report_url: `/api/trajectory/report`,
      html_url: `/api/trajectory/report?format=html`,
    });
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// 查看最新人话版报告（每次访问均重新生成, 保证数据最新）
// 默认返回 Markdown; 支持 ?format=html 或 Accept: text/html 返回 HTML 版本.
app.get('/api/trajectory/report', (req, res) => {
  try {
    const report = buildTrajectoryReport();
    const accept = req.headers.accept || '';
    const wantsHtml = req.query.format === 'html' || accept.includes('text/html');
    if (wantsHtml) {
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.send(buildTrajectoryReportHTML(report));
    } else {
      res.setHeader('Content-Type', 'text/markdown; charset=utf-8');
      res.send(report.mdContent);
    }
  } catch (e) {
    res.status(500).json(errorResponse(e));
  }
});

// ── API: 提交文本管线任务 (Mode A) ────────────────────────


};
