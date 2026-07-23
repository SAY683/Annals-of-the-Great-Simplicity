/* TRACE Engine Web — 参数 Schema 与预设处理（debt-09 + debt-16）
 * ============================================================
 * 抽取自原 index.html 内联 <script>。
 *
 * debt-16：删除硬编码的 PRESETS_OVERRIDES / FALLBACK_SCHEMA / SUPER_FALLBACK_SCHEMA，
 *          改为运行时从 /api/schema 与 /api/presets 动态加载；
 *          仅保留极简 inline 兜底，用于 /api/config 不可达的离线开发场景。
 * debt-10：同时从 /api/schema 拉取 resultSchema，供 render.js 动态渲染。
 *
 * 依赖（运行时由 app.js / render.js 提供）：
 *   - log(level, message)         由 render.js 提供
 *   - dynamicParams (DOM)         由 app.js 提供
 *   - superModelSelect (DOM)      由 app.js 提供
 *   - modelBadge (DOM)            由 app.js 提供
 */

// ── 运行时 Schema 状态（跨脚本共享） ──────────────────────────────────
let BRIDGE_SCHEMA = null;
let SUPER_BRIDGE_SCHEMA = null;
let RESULT_SCHEMA = null;      // debt-10：结果 Schema，供 render.js 使用
let PRESETS = null;            // debt-16：从 /api/presets 动态加载，替代 PRESETS_OVERRIDES

// 极简离线兜底（仅当 /api/config 完全不可达时使用，debt-16 大幅精简）
const _OFFLINE_FALLBACK_SCHEMA = {
  threshold: { type: 'number', min: 0, max: 10, default: 0.03, description: '因果边显著性阈值' },
  window_size: { type: 'integer', min: 2, max: 256, default: 64, description: 'TRACE 滑动窗口大小' },
  max_segments: { type: 'integer', min: 1, max: 16, default: 4, description: 'LLaMA TRACE 最大分段数' },
  max_concepts: { type: 'integer', min: 1, max: 128, default: 12, description: '最大概念数' },
  concept_min_freq: { type: 'integer', min: 1, max: 1000, default: 2, description: '概念最小出现频次' },
  min_valid_tokens: { type: 'integer', min: 1, max: 10000, default: 10, description: '最小有效 token 数' },
  min_concepts: { type: 'integer', min: 2, max: 128, default: 3, description: '最小概念数' },
  max_edges_for_dowhy: { type: 'integer', min: 1, max: 100, default: 8, description: '传入 DoWhy 的最大边数' },
  filter_mode: { type: 'string', default: 'topn', description: '边过滤模式 (topn / percentile / adaptive)' },
  filter_percentile: { type: 'integer', min: 50, max: 99, default: 85, description: 'percentile 模式的百分位' },
  random_state: { type: 'integer', min: 0, max: 999999, default: 42, description: '随机种子' },
  classical_mode: { type: 'boolean', default: false, description: '古汉语模式' },
};

const _OFFLINE_FALLBACK_SUPER_SCHEMA = Object.assign({}, _OFFLINE_FALLBACK_SCHEMA, {
  threshold: { type: 'number', min: 0, max: 10, default: 0.01, description: '因果边显著性阈值（LLaMA 专属）' },
  window_size: { type: 'integer', min: 2, max: 256, default: 128, description: 'TRACE 滑动窗口大小（LLaMA 专属）' },
  max_segments: { type: 'integer', min: 1, max: 16, default: 3, description: 'LLaMA TRACE 最大分段数（LLaMA 专属）' },
  concept_min_freq: { type: 'integer', min: 1, max: 1000, default: 1, description: '概念最小出现频次（LLaMA 专属）' },
  max_edges_for_dowhy: { type: 'integer', min: 1, max: 100, default: 12, description: '传入 DoWhy 的最大边数' },
});

// 极简离线预设兜底（仅当 /api/presets 不可达时使用）
// 预设名与服务端 presets.yaml 对齐：demo/standard/deep/archival/llama
// 同时保留旧名称别名（default→demo, sensitive→standard, broad→archival）兼容旧前端按钮
const _OFFLINE_PRESETS = {
  demo: { threshold: 0.03, window_size: 8, max_segments: 4, min_valid_tokens: 10 },
  default: { threshold: 0.03, window_size: 8, max_segments: 4, min_valid_tokens: 10 },
  standard: { threshold: 0.03, window_size: 6, max_concepts: 16, concept_min_freq: 2, max_segments: 3, min_valid_tokens: 8 },
  sensitive: { threshold: 0.03, window_size: 6, max_concepts: 16, concept_min_freq: 2, max_segments: 3, min_valid_tokens: 8 },
  archival: { threshold: 0.8, window_size: 12, max_concepts: 24, max_segments: 6, min_valid_tokens: 12 },
  broad: { threshold: 0.8, window_size: 12, max_concepts: 24, max_segments: 6, min_valid_tokens: 12 },
  deep: { threshold: 0.2, window_size: 8, max_concepts: 24, max_edges_for_dowhy: 15, filter_mode: 'percentile', filter_percentile: 80, max_segments: 4, min_valid_tokens: 10 },
  llama: { threshold: 0.01, window_size: 128, max_segments: 3, max_concepts: 12, concept_min_freq: 1, max_edges_for_dowhy: 12, filter_mode: 'topn', filter_percentile: 85, classical_mode: false, min_valid_tokens: 10 },
};

function formatParamLabel(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function renderParams(schema) {
  if (!dynamicParams) return;
  dynamicParams.innerHTML = '';
  const keys = Object.keys(schema);
  if (keys.length === 0) {
    dynamicParams.innerHTML = '<div class="param"><span class="k">No parameters</span></div>';
    return;
  }
  keys.forEach(key => {
    const meta = schema[key];
    const div = document.createElement('div');
    div.className = 'param';
    const label = formatParamLabel(key);
    const step = meta.type === 'integer' ? 1 : (meta.step || 0.1);
    if (meta.type === 'string') {
      div.innerHTML = `<span class="k" title="${escapeHtml(meta.description || '')}">${label}</span>
        <input type="text" id="param-${key}" value="${escapeHtml(String(meta.default ?? ''))}" style="width:110px;background:var(--bg-elevated);border:1px solid var(--border);color:var(--text);border-radius:4px;padding:0.25rem;">`;
    } else {
      div.innerHTML = `<span class="k" title="${escapeHtml(meta.description || '')}">${label}</span>
        <input type="number" id="param-${key}" value="${meta.default ?? 0}" step="${step}" min="${meta.min ?? ''}" max="${meta.max ?? ''}" style="width:80px;background:var(--bg-elevated);border:1px solid var(--border);color:var(--text);border-radius:4px;padding:0.25rem;">`;
    }
    dynamicParams.appendChild(div);
  });
}

function getCurrentSchema() {
  const mode = document.querySelector('input[name="mode"]:checked')?.value || 'light';
  if (mode === 'super') {
    return SUPER_BRIDGE_SCHEMA || _OFFLINE_FALLBACK_SUPER_SCHEMA;
  }
  return BRIDGE_SCHEMA || _OFFLINE_FALLBACK_SCHEMA;
}

function getConfig() {
  const schema = getCurrentSchema();
  const cfg = {};
  Object.keys(schema).forEach(key => {
    const meta = schema[key];
    const el = document.getElementById(`param-${key}`);
    if (!el) return;
    let raw = el.value.trim();
    if (meta.type === 'string') {
      cfg[key] = raw;
    } else if (meta.type === 'integer') {
      // P2-3：parseInt 可能返回 NaN（空串/非法输入），NaN 时回退到 schema 默认值
      const parsed = parseInt(raw, 10);
      cfg[key] = Number.isNaN(parsed) ? (meta.default ?? 0) : parsed;
    } else {
      // P2-3：parseFloat 同样需要 NaN 检查并回退默认值
      const parsed = parseFloat(raw);
      cfg[key] = Number.isNaN(parsed) ? (meta.default ?? 0) : parsed;
    }
  });
  return cfg;
}

/**
 * debt-16：从 /api/config 加载 bridgeParamSchema / superBridgeParamSchema，
 *          从 /api/schema 加载 resultSchema（debt-10），
 *          从 /api/presets 加载预设参数（替代 PRESETS_OVERRIDES）。
 */
async function loadBridgeSchema() {
  // 并行拉取三份契约
  const [configRes, schemaRes, presetsRes] = await Promise.allSettled([
    fetch('/api/config').then(r => r.json()),
    fetch('/api/schema').then(r => r.json()),
    fetch('/api/presets').then(r => r.json()),
  ]);

  // 1. bridgeParamSchema（来自 /api/config）
  if (configRes.status === 'fulfilled' && configRes.value.success) {
    const data = configRes.value;
    if (data.bridgeParamSchema && Object.keys(data.bridgeParamSchema).length > 0) {
      BRIDGE_SCHEMA = data.bridgeParamSchema;
      log('info', `已加载动态参数 Schema (${Object.keys(BRIDGE_SCHEMA).length} 项)`);
    } else {
      BRIDGE_SCHEMA = _OFFLINE_FALLBACK_SCHEMA;
      log('warn', '/api/config 未返回 Schema，使用离线兜底配置');
    }
    // 根据服务端探测结果动态填充 LLaMA 模型选项
    if (data.llamaModels && Array.isArray(data.llamaModels.available)) {
      populateModelSelect(data.llamaModels.available, data.llamaModels.default);
    }
    if (data.superBridgeParamSchema && Object.keys(data.superBridgeParamSchema).length > 0) {
      SUPER_BRIDGE_SCHEMA = data.superBridgeParamSchema;
    }
  } else {
    BRIDGE_SCHEMA = _OFFLINE_FALLBACK_SCHEMA;
    log('warn', '加载 /api/config 失败，使用离线兜底 Schema');
  }

  // 2. resultSchema（来自 /api/schema，debt-10）
  if (schemaRes.status === 'fulfilled' && schemaRes.value.success) {
    RESULT_SCHEMA = schemaRes.value.resultSchema || null;
    if (RESULT_SCHEMA) {
      log('info', `已加载结果 Schema (required: ${RESULT_SCHEMA.required?.length || 0} 项)`);
    }
  }

  // 3. presets（来自 /api/presets，debt-16）
  if (presetsRes.status === 'fulfilled' && presetsRes.value.success) {
    PRESETS = presetsRes.value.presets || null;
    if (PRESETS) {
      log('info', `已加载参数预设 (${Object.keys(PRESETS).length} 套)`);
    }
  } else {
    PRESETS = _OFFLINE_PRESETS;
    log('warn', '加载 /api/presets 失败，使用离线兜底预设');
  }

  renderParams(BRIDGE_SCHEMA);
}

function populateModelSelect(models, defaultId) {
  if (!superModelSelect) return;
  // 探测失败时保留兜底选项，避免 SUPER 模式无模型可选
  if (!models || models.length === 0) {
    updateModelBadge();
    return;
  }
  superModelSelect.innerHTML = '';
  models.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    const isEgg = m.id.includes('shenji');
    opt.textContent = `${m.name}${isEgg ? ' [EGG]' : ' [SPEED]'}`;
    superModelSelect.appendChild(opt);
  });
  if (defaultId) superModelSelect.value = defaultId;
  updateModelBadge();
}

/**
 * debt-16：应用参数预设。从 /api/presets 返回的 PRESETS 中取值，
 *          未命中的字段回退到当前 Schema 的 default 值。
 * 竣工审查修复：前端按钮预设名（default/sensitive/broad）与服务端
 *          presets.yaml 预设名（demo/standard/archival）不一致，
 *          通过别名映射表兼容两端。
 */
const _PRESET_ALIASES = {
  default: 'demo',
  sensitive: 'standard',
  broad: 'archival',
};

function applyPreset(presetName) {
  const schema = BRIDGE_SCHEMA || _OFFLINE_FALLBACK_SCHEMA;
  // 先尝试原名，再尝试别名映射
  const resolvedName = _PRESET_ALIASES[presetName] || presetName;
  const overrides = (PRESETS && (PRESETS[presetName] || PRESETS[resolvedName]))
    || _OFFLINE_PRESETS[presetName]
    || _OFFLINE_PRESETS[resolvedName]
    || {};
  Object.keys(schema).forEach(key => {
    const el = document.getElementById(`param-${key}`);
    if (!el) return;
    const meta = schema[key];
    let value = overrides[key] !== undefined ? overrides[key] : meta.default;
    el.value = value;
  });
  log('info', `已加载参数预设: ${presetName.toUpperCase()}${resolvedName !== presetName ? ` (→${resolvedName})` : ''}`);
}
