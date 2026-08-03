/**
 * TRACE Engine Web — API Key 鉴权中间件（debt-12）
 * =====================================
 * 分级保护：
 *   - 公开只读：/api/health、/api/version、/api/schema、/api/presets
 *   - 需鉴权：/api/analyze-*、/api/result/:id、/api/report/:id、/api/jobs*
 *   - 管理员：/api/admin/cleanup、/api/jobs/clear（需要 TRACE_ADMIN_KEY）
 *
 * 鉴权方式：通过 Authorization: Bearer <key> 或 X-Api-Key 头携带密钥。
 * 未设置 TRACE_API_KEY 时跳过鉴权（开发模式兼容）。
 */
const utils = require('../lib/utils');
const { logToFile } = utils;

// 公开只读路径（无需鉴权）
const PUBLIC_PATHS = new Set([
  '/api/health',
  '/api/version',
  '/api/schema',
  '/api/presets',
]);

// 管理员路径（需要 TRACE_ADMIN_KEY）
const ADMIN_PATHS = new Set([
  '/api/admin/cleanup',
  '/api/jobs/clear',
  // P0-3 修复 (Round 27 审计): 批量删除属破坏性操作，原未纳入 ADMIN_PATHS，
  // 普通用户持 apiKey 即可清空他人任务历史。
  '/api/jobs/batch-delete',
]);

// 动态管理员路径（需正则匹配，配合 req.method 判定）
// DELETE /api/jobs/:id —— 单条删除同样属破坏性操作，需管理员密钥
const ADMIN_PATH_RE = /^\/api\/jobs\/[a-f0-9-]{8,}(\.json)?$/i;

function _isAdminRequest(req) {
  const reqPath = req.path;
  if (ADMIN_PATHS.has(reqPath)) return true;
  // DELETE /api/jobs/:id 动态路径：UUID 校验 + 方法限定
  if (req.method === 'DELETE' && ADMIN_PATH_RE.test(reqPath)) return true;
  return false;
}

function _extractApiKey(req) {
  // 优先 Authorization: Bearer <key>
  const auth = req.headers['authorization'];
  if (auth && /^bearer\s+/i.test(auth)) {
    return auth.replace(/^bearer\s+/i, '').trim();
  }
  // 兼容 X-Api-Key 头
  const xKey = req.headers['x-api-key'];
  if (xKey) return String(xKey).trim();

  // P0-6 修复 (ROUND27 12维度核对): query 参数 ?api_key= 仅对 GET 请求放行,
  // 禁止 POST/DELETE 的 query 鉴权 —— 攻击者可通过 <img src="...?api_key=LEAKED">
  // 发起 CSRF 执行破坏性操作 (清空历史/删除任务). GET 请求无副作用, 保留 query
  // 鉴权便于浏览器直接访问只读 API.
  const isDestructiveMethod = ['POST', 'DELETE', 'PUT', 'PATCH'].includes(req.method);
  const isAdminPath = _isAdminRequest(req);
  if (!isDestructiveMethod && !isAdminPath && req.query && req.query.api_key) {
    return String(req.query.api_key).trim();
  }
  return null;
}

function _constantTimeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  // P2-12 修复 (ROUND27 12维度核对): 原 `if (a.length !== b.length) return false`
  // 在长度不等时早返回, 攻击者可通过响应时间侧信道推断密钥长度.
  // 现将长度差异合并到 diff, 遍历较短长度, 最后统一返回.
  const minLen = Math.min(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < minLen; i++) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

/**
 * 创建鉴权中间件。
 * @returns {Function} Express 中间件
 */
function createAuthMiddleware() {
  const apiKey = process.env.TRACE_API_KEY || '';
  const adminKey = process.env.TRACE_ADMIN_KEY || '';
  const authEnabled = !!apiKey;

  if (!authEnabled) {
    logToFile('warn', 'TRACE_API_KEY 未设置，API 鉴权已禁用（开发模式）。生产环境请设置 TRACE_API_KEY 与 TRACE_ADMIN_KEY。');
  }

  return function authMiddleware(req, res, next) {
    // 鉴权未启用：直接放行
    if (!authEnabled) return next();

    const reqPath = req.path;
    // 静态资源与非 /api/ 且非 /mcp 路径放行
    // P0 修缮（2026-08-03）: 原版仅保护 /api/, 导致 /mcp (MCP JSON-RPC 端点) 完全
    // 绕过鉴权 —— 攻击者可直接 POST /mcp 调用 analyze_text 等工具耗尽 GPU 资源。
    // 现将 /mcp 纳入鉴权范围, 与 /api/ 同等保护。
    if (!reqPath || (!reqPath.startsWith('/api/') && !reqPath.startsWith('/mcp'))) return next();

    // 公开只读路径放行
    if (PUBLIC_PATHS.has(reqPath)) return next();

    // 提取请求中的 API Key
    const providedKey = _extractApiKey(req);

    // debt-12 audit 修复：原实现先校验 providedKey == apiKey，
    // 导致管理员用 adminKey 调用管理员路径时被 401 拒绝。
    // 现改为：管理员路径优先校验 adminKey，普通路径校验 apiKey。

    // 管理员路径：优先校验 TRACE_ADMIN_KEY
    if (_isAdminRequest(req)) {
      if (!adminKey) {
        logToFile('warn', `管理员操作被拒：TRACE_ADMIN_KEY 未设置 path=${reqPath}`);
        return res.status(403).json({
          success: false,
          error: '管理员操作被拒：服务端未配置 TRACE_ADMIN_KEY',
          code: 'ADMIN_KEY_NOT_CONFIGURED',
          traceId: req.traceId,
        });
      }
      if (!providedKey || !_constantTimeEqual(providedKey, adminKey)) {
        logToFile('warn', `管理员操作被拒：密钥不匹配 path=${reqPath} traceId=${req.traceId || '-'}`);
        return res.status(403).json({
          success: false,
          error: '禁止访问：需要管理员密钥',
          code: 'FORBIDDEN',
          traceId: req.traceId,
        });
      }
      return next();
    }

    // 普通鉴权路径：校验 TRACE_API_KEY
    if (!providedKey || !_constantTimeEqual(providedKey, apiKey)) {
      logToFile('warn', `鉴权失败 path=${reqPath} traceId=${req.traceId || '-'}`);
      return res.status(401).json({
        success: false,
        error: '未授权：缺少或无效的 API Key',
        code: 'UNAUTHORIZED',
        traceId: req.traceId,
      });
    }

    next();
  };
}

module.exports = {
  createAuthMiddleware,
  PUBLIC_PATHS,
  ADMIN_PATHS,
};
