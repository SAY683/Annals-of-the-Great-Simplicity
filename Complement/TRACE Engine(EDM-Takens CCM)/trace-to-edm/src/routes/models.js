module.exports = function mount(app, ctx) {
const { fs, path, spawn, crypto, ROOT, PROJECTS_DIR, TRAJECTORY_CSV, PYTHON_CMD, BRIDGE_SCRIPT, PACKAGE_VERSION, serverLog, reqLog, getActiveTrajectoryCSV, pyCall, pyScript, errorResponse, activeJobs, jobHistory, createJobId, emitSSE, streamBridgeProcess, readTrajectoryCSV, buildTrajectoryReport, buildTrajectoryReportHTML, getCached, setCached, invalidateCache, pyDS, getDatasetExports, markDatasetProcessed, pipelineState } = ctx;

app.get('/api/models', async (_req, res) => {
  // P1-b：服务端 5s 内存缓存，减少 Python 冷启动开销
  const cached = getCached('models');
  if (cached) return res.json(cached);
  try {
    const script = "import sys, json; sys.path.insert(0, '.'); from layer3_sacred import list_models, get_active_model; print(json.dumps({'models': list_models(), 'active': get_active_model()}, ensure_ascii=False))";
    const result = await pyScript(script, 30000);
    let payload;
    try { payload = JSON.parse(result.out); } catch { payload = { error: result.out }; }
    setCached('models', payload);
    res.json(payload);
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

app.post('/api/models/activate', async (req, res) => {
  const { model } = req.body;
  if (!model) return res.status(400).json({ error: 'model key required' });

  // 元审计 P1 修缮: Python 注入防护
  // 之前用字符串拼接 + replace(/'/g, '') 不够健壮
  // 现采用白名单校验 + JSON 参数传递，彻底消除注入
  // Q9 P1-16 修复: TRACE LLaMA 模型仅在前端展示，不允许在 L3 直接激活
  const ALLOWED_MODELS = ['qwen2.5-1.5b', 'qwen2.5-3b'];
  if (!ALLOWED_MODELS.includes(model)) {
    return res.status(400).json({
      error: `invalid model key: ${model}`,
      allowed: ALLOWED_MODELS,
      note: 'shehui-llama / shenji-llama 为 TRACE LLaMA 展示模型，请使用 trace-engine-web SUPER 模式',
    });
  }

  try {
    // 用 JSON 序列化传递参数，避免任何字符串拼接
    const modelJson = JSON.stringify(model);
    const script = `import sys, json; sys.path.insert(0, '.'); from layer3_sacred import set_active_model, get_active_model; ok = set_active_model(json.loads('${modelJson}')); print(json.dumps({'success': ok, 'active': get_active_model()}, ensure_ascii=False))`;
    const result = await pyScript(script, 15000);
    let payload;
    try { payload = JSON.parse(result.out); } catch { payload = { success: false }; }
    if (!payload.success) {
      return res.status(400).json({
        error: `model '${model}' cannot be activated (展示模型或未注册)`,
        allowed: ALLOWED_MODELS.filter(k => !['shehui-llama','shenji-llama'].includes(k)),
      });
    }
    // P1-b：模型切换后失效缓存，确保下次 GET /api/models 返回最新状态
    invalidateCache('models');
    res.json(payload);
  } catch (e) { res.status(500).json(errorResponse(e)); }
});

};
