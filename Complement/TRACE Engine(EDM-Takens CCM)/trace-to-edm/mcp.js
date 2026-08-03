/**
 * trace-to-edm MCP 适配模块
 * ==========================
 * 为 trace-to-edm 补齐 MCP (Model Context Protocol) 协议端点。
 * 端点: POST /mcp  (JSON-RPC 2.0)
 *
 * 工具映射:
 *   run_pipeline   → POST /api/run
 *   trigger_edm    → POST /api/edm/trigger
 *   get_trajectory → GET  /api/trajectory
 *   list_projects  → GET  /api/projects
 *   list_models    → GET  /api/models
 *   get_dataset    → GET  /api/dataset
 *   health         → GET  /api/health
 *   version        → GET  /api/version
 */

const http = require('http');

const TOOLS = [
  {
    name: 'run_pipeline',
    description: '运行 TRACE 文本管线（处理数据集中的待处理条目）。LIGHT 模式用 jieba 分词，DEEP 模式用六战士算法。',
    inputSchema: {
      type: 'object',
      properties: {
        mode: { type: 'string', enum: ['light', 'deep'], default: 'light', description: 'TRACE 模式: light=1-3s/条(jieba), deep=10-60s/条(六战士)' }
      }
    }
  },
  {
    name: 'trigger_edm',
    description: '触发 EDM 分析（含反馈检测），基于轨迹数据进行动力学重建和预测。',
    inputSchema: {
      type: 'object',
      properties: {
        target: { type: 'string', default: 'ate', description: '预测目标: ate/adj_density/max_delta_nll/ci_width/edge_count/ccm_coverage_pct' },
        steps: { type: 'integer', default: 3, description: '预测步数: 1/3/5/10' }
      }
    }
  },
  {
    name: 'get_trajectory',
    description: '查询轨迹数据（TRACE 产出的因果指标时间序列）。',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'list_projects',
    description: '列出所有项目及其数据条目数。',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'list_models',
    description: '列出可用的 LLM 模型（Qwen2.5-1.5B/3B 等）。',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'get_dataset',
    description: '获取当前项目的数据集（回填条目 + 文本条目 + 处理状态）。',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'health',
    description: '检查服务健康状态。',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'version',
    description: '获取服务版本信息。',
    inputSchema: { type: 'object', properties: {} }
  }
];

// P1 修缮（2026-08-03）: 新增 fwdHeaders 参数, 透传鉴权头 (X-API-Key/Authorization)。
// 生产模式下 CROSS_PROJECT_API_KEY 已设置, /api/* 端点会校验 X-API-Key,
// 若不透传则 MCP → /api/* 的内部调用会被 401 拒绝。
// 与 edm-takens-web/backend/mcp.py 的 P1 修缮对齐。
function _localFetch(port, method, path, body, fwdHeaders) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const headers = data
      ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) }
      : {};
    // P1 修缮: 透传鉴权头到内部 localhost 调用
    if (fwdHeaders) {
      for (const [k, v] of Object.entries(fwdHeaders)) {
        headers[k] = v;
      }
    }
    const options = { hostname: '127.0.0.1', port, path, method, headers };
    const req = http.request(options, (res) => {
      let chunks = '';
      res.on('data', (c) => chunks += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, json: chunks ? JSON.parse(chunks) : null, text: chunks }); }
        catch (e) { resolve({ status: res.statusCode, json: null, text: chunks }); }
      });
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

async function callTool(name, args, port, fwdHeaders) {
  const a = args || {};
  const fh = fwdHeaders || {};
  switch (name) {
    case 'run_pipeline':
      return await _localFetch(port, 'POST', '/api/run', { mode: a.mode || 'light' }, fh);
    case 'trigger_edm':
      return await _localFetch(port, 'POST', '/api/edm/trigger', { target: a.target || 'ate', steps: a.steps || 3 }, fh);
    case 'get_trajectory':
      return await _localFetch(port, 'GET', '/api/trajectory', null, fh);
    case 'list_projects':
      return await _localFetch(port, 'GET', '/api/projects', null, fh);
    case 'list_models':
      return await _localFetch(port, 'GET', '/api/models', null, fh);
    case 'get_dataset':
      return await _localFetch(port, 'GET', '/api/dataset', null, fh);
    case 'health':
      return await _localFetch(port, 'GET', '/api/health', null, fh);
    case 'version':
      return await _localFetch(port, 'GET', '/api/version', null, fh);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

function createMcpRouter(port) {
  const express = require('express');
  const router = express.Router();
  router.use(express.json({ limit: '10mb' }));

  router.post('/', async (req, res) => {
    const { jsonrpc, method, params, id } = req.body || {};
    if (jsonrpc !== '2.0') {
      return res.json({ jsonrpc: '2.0', id: id || null, error: { code: -32600, message: 'Invalid Request: jsonrpc must be "2.0"' } });
    }
    if (method === 'initialize') {
      return res.json({
        jsonrpc: '2.0', id,
        result: {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {} },
          serverInfo: { name: 'trace-to-edm-mcp', version: '0.1.0' }
        }
      });
    }
    if (method === 'tools/list') {
      return res.json({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
    }
    if (method === 'tools/call') {
      const { name, arguments: args } = params || {};
      if (!name) return res.json({ jsonrpc: '2.0', id, error: { code: -32602, message: 'params.name is required' } });
      try {
        // P1 修缮（2026-08-03）: 提取鉴权头, 透传给内部 localhost 调用。
        // 生产模式 (CROSS_PROJECT_API_KEY 已设置) 下 /api/* 端点会校验 X-API-Key,
        // 若不透传则 MCP → /api/* 内部调用会被 401 拒绝。
        const fwdHeaders = {};
        for (const h of ['x-api-key', 'authorization']) {
          const v = req.get(h);
          if (v) fwdHeaders[h] = v;
        }
        const result = await callTool(name, args, port, fwdHeaders);
        const content = result.json !== null ? JSON.stringify(result.json, null, 2) : result.text;
        return res.json({ jsonrpc: '2.0', id, result: { content: [{ type: 'text', text: content }], isError: result.status >= 400 } });
      } catch (err) {
        return res.json({ jsonrpc: '2.0', id, error: { code: -32603, message: `Tool execution failed: ${err.message}` } });
      }
    }
    return res.json({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
  });

  router.get('/', (_req, res) => {
    res.json({
      service: 'trace-to-edm-mcp', version: '0.1.0', protocolVersion: '2024-11-05',
      endpoint: 'POST /mcp', methods: ['initialize', 'tools/list', 'tools/call'],
      toolCount: TOOLS.length, tools: TOOLS.map(t => t.name)
    });
  });
  return router;
}

module.exports = { createMcpRouter, TOOLS };
