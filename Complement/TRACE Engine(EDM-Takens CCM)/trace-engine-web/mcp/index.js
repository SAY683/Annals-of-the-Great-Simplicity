/**
 * trace-engine-web MCP 适配模块
 * ==============================
 * 为 trace-engine-web 补齐 MCP (Model Context Protocol) 协议端点。
 * 采用轻量级 JSON-RPC 2.0 over HTTP 实现，支持:
 *   - initialize: 协议握手
 *   - tools/list: 列出可用工具
 *   - tools/call: 调用工具（内部通过 localhost fetch 复用现有路由）
 *
 * 端点: POST /mcp
 *
 * 设计原则:
 *   1. 不侵入现有路由代码 — MCP 模块完全独立，可插拔
 *   2. 复用现有路由逻辑 — 通过 localhost fetch 调用，继承校验/错误处理/trace_id
 *   3. 无新依赖 — 仅用 Node.js 内置 http 模块
 */

const http = require('http');

// ── 工具定义 ──────────────────────────────────────────────
const TOOLS = [
  {
    name: 'analyze_text',
    description: '对文本进行因果推断分析（TRACE Engine）。输入描述因果关系的文本，返回 ATE、因果边、概念列表等。短文本（<10词）会被拒绝。',
    inputSchema: {
      type: 'object',
      properties: {
        text: { type: 'string', description: '待分析的文本（建议 ≥10 个有效词）' },
        mode: { type: 'string', enum: ['light', 'deep', 'super'], default: 'light', description: '分析模式: light=快速共现, deep=六战士, super=LLaMA ΔNLL' }
      },
      required: ['text']
    }
  },
  {
    name: 'list_jobs',
    description: '列出因果推断任务历史（最近50条）。',
    inputSchema: { type: 'object', properties: {} }
  },
  {
    name: 'get_job',
    description: '查询单个任务的状态和元数据。',
    inputSchema: {
      type: 'object',
      properties: { id: { type: 'string', description: '任务 UUID' } },
      required: ['id']
    }
  },
  {
    name: 'get_job_detail',
    description: '获取任务详情（聚合输入文本 + result.json + report.md）。',
    inputSchema: {
      type: 'object',
      properties: { id: { type: 'string', description: '任务 UUID' } },
      required: ['id']
    }
  },
  {
    name: 'get_result',
    description: '获取任务的完整分析结果（result.json）。',
    inputSchema: {
      type: 'object',
      properties: { id: { type: 'string', description: '任务 UUID' } },
      required: ['id']
    }
  },
  {
    name: 'export_md',
    description: '导出任务的人话版 Markdown 报告（非技术读者可理解）。',
    inputSchema: {
      type: 'object',
      properties: { id: { type: 'string', description: '任务 UUID' } },
      required: ['id']
    }
  },
  {
    name: 'health',
    description: '检查服务健康状态（skill/python 就绪情况）。',
    inputSchema: { type: 'object', properties: {} }
  }
];

// ── 内部 HTTP 调用（localhost fetch）──────────────────────
// P1 修缮（2026-08-03）: 新增 fwdHeaders 参数, 透传鉴权头 (X-API-Key/Authorization)。
// 生产模式下 TRACE_API_KEY 已设置, /api/* 端点会校验 X-API-Key,
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
        try {
          resolve({ status: res.statusCode, json: chunks ? JSON.parse(chunks) : null, text: chunks });
        } catch (e) {
          resolve({ status: res.statusCode, json: null, text: chunks });
        }
      });
    });
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

// ── 工具调用分发 ──────────────────────────────────────────
async function callTool(name, args, port, fwdHeaders) {
  const a = args || {};
  const fh = fwdHeaders || {};
  switch (name) {
    case 'analyze_text':
      return await _localFetch(port, 'POST', '/api/analyze-text', { text: a.text, mode: a.mode || 'light' }, fh);
    case 'list_jobs':
      return await _localFetch(port, 'GET', '/api/jobs', null, fh);
    case 'get_job':
      return await _localFetch(port, 'GET', `/api/jobs/${encodeURIComponent(a.id)}`, null, fh);
    case 'get_job_detail':
      return await _localFetch(port, 'GET', `/api/jobs/${encodeURIComponent(a.id)}/detail`, null, fh);
    case 'get_result':
      return await _localFetch(port, 'GET', `/api/result/${encodeURIComponent(a.id)}`, null, fh);
    case 'export_md':
      return await _localFetch(port, 'GET', `/api/jobs/${encodeURIComponent(a.id)}/export/md`, null, fh);
    case 'health':
      return await _localFetch(port, 'GET', '/api/health', null, fh);
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

// ── MCP JSON-RPC 路由 ────────────────────────────────────
function createMcpRouter(port) {
  const express = require('express');
  const router = express.Router();

  router.use(express.json({ limit: '10mb' }));

  router.post('/', async (req, res) => {
    const { jsonrpc, method, params, id } = req.body || {};

    // JSON-RPC 2.0 协议校验
    if (jsonrpc !== '2.0') {
      return res.json({ jsonrpc: '2.0', id: id || null, error: { code: -32600, message: 'Invalid Request: jsonrpc must be "2.0"' } });
    }

    // initialize
    if (method === 'initialize') {
      return res.json({
        jsonrpc: '2.0', id,
        result: {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {} },
          serverInfo: { name: 'trace-engine-web-mcp', version: '0.1.0' }
        }
      });
    }

    // tools/list
    if (method === 'tools/list') {
      return res.json({ jsonrpc: '2.0', id, result: { tools: TOOLS } });
    }

    // tools/call
    if (method === 'tools/call') {
      const { name, arguments: args } = params || {};
      if (!name) {
        return res.json({ jsonrpc: '2.0', id, error: { code: -32602, message: 'params.name is required' } });
      }
      try {
        // P1 修缮（2026-08-03）: 提取鉴权头, 透传给内部 localhost 调用。
        // 生产模式 (TRACE_API_KEY 已设置) 下 /api/* 端点会校验 X-API-Key,
        // 若不透传则 MCP → /api/* 内部调用会被 401 拒绝。
        const fwdHeaders = {};
        for (const h of ['x-api-key', 'authorization']) {
          const v = req.get(h);
          if (v) fwdHeaders[h] = v;
        }
        const result = await callTool(name, args, port, fwdHeaders);
        // 将 HTTP 响应包装为 MCP content
        const content = result.json !== null
          ? JSON.stringify(result.json, null, 2)
          : result.text;
        return res.json({
          jsonrpc: '2.0', id,
          result: {
            content: [{ type: 'text', text: content }],
            isError: result.status >= 400
          }
        });
      } catch (err) {
        return res.json({ jsonrpc: '2.0', id, error: { code: -32603, message: `Tool execution failed: ${err.message}` } });
      }
    }

    // 未知方法
    return res.json({ jsonrpc: '2.0', id, error: { code: -32601, message: `Method not found: ${method}` } });
  });

  // GET /mcp — 返回服务信息（便于浏览器访问确认）
  router.get('/', (_req, res) => {
    res.json({
      service: 'trace-engine-web-mcp',
      version: '0.1.0',
      protocolVersion: '2024-11-05',
      endpoint: 'POST /mcp',
      methods: ['initialize', 'tools/list', 'tools/call'],
      toolCount: TOOLS.length,
      tools: TOOLS.map(t => t.name)
    });
  });

  return router;
}

module.exports = { createMcpRouter, TOOLS };
