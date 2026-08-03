/**
 * shared/auth_middleware.js — 跨项目共享的 API Key 认证中间件
 * ============================================================
 * 适用项目: trace-to-edm / trace-engine-web / 其他需要 API Key 鉴权的 Node.js 服务
 *
 * 盲审 P0-3 修缮 (2026-08-02):
 *   trace-to-edm/server.js:313 `require('../shared/auth_middleware')` 引用了不存在的文件,
 *   生产模式 (NODE_ENV=production) 下直接 process.exit(1) 导致服务无法启动.
 *   本模块补齐该缺失依赖, 提供真实的 API Key 鉴权 + 环回地址放行能力.
 *
 * 配置:
 *   - CROSS_PROJECT_API_KEY 环境变量: 设置后启用强鉴权, 所有 /api/ 请求需带
 *     X-API-Key 头 (或 Authorization: Bearer <key>) 才能访问
 *   - 未设置 CROSS_PROJECT_API_KEY: 开发模式, 自动放行环回地址 (127.0.0.1/::1)
 *     外部连接返回 403
 *
 * 使用方式:
 *   const { createAuthMiddleware } = require('../shared/auth_middleware');
 *   app.use(createAuthMiddleware({ excludePaths: ['/api/health'] }));
 */

const crypto = require('crypto');

/**
 * 创建认证中间件
 * @param {Object} options
 * @param {string[]} options.excludePaths - 免鉴权路径列表 (如 ['/api/health', '/api/version'])
 * @param {string} options.apiKeyEnv - API Key 环境变量名 (默认 'CROSS_PROJECT_API_KEY')
 * @param {string} options.headerName - API Key 请求头名 (默认 'x-api-key')
 * @returns {Function} Express middleware
 */
function createAuthMiddleware(options = {}) {
  const excludePaths = new Set(options.excludePaths || ['/api/health']);
  const apiKeyEnv = options.apiKeyEnv || 'CROSS_PROJECT_API_KEY';
  const headerName = (options.headerName || 'x-api-key').toLowerCase();
  const configuredKey = process.env[apiKeyEnv];

  return function authMiddleware(req, res, next) {
    // 1. 免鉴权路径放行 (健康检查/版本查询等无敏感数据)
    if (excludePaths.has(req.path)) {
      return next();
    }

    // 2. 强鉴权模式: 已配置 API Key
    if (configuredKey) {
      const providedKey = req.headers[headerName] ||
        (req.headers['authorization'] || '').replace(/^Bearer\s+/i, '');
      if (!providedKey) {
        return res.status(401).json({
          error: 'API key required',
          code: 'AUTH_MISSING',
          hint: `Provide via ${headerName} header or Authorization: Bearer <key>`,
        });
      }
      // 常量时间比较防时序攻击
      const a = Buffer.from(String(providedKey));
      const b = Buffer.from(String(configuredKey));
      if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
        return res.status(403).json({
          error: 'Invalid API key',
          code: 'AUTH_INVALID',
        });
      }
      return next();
    }

    // 3. 开发模式 (未配置 API Key): 仅允许环回地址
    const ip = req.ip || (req.connection && req.connection.remoteAddress) || '';
    const isLoopback = ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1';
    if (isLoopback) {
      return next();
    }

    // 4. 非环回地址 + 未配置 API Key = 拒绝外部访问
    return res.status(403).json({
      error: 'External access denied — set ' + apiKeyEnv + ' to enable API key auth',
      code: 'AUTH_FALLBACK',
      client_ip: ip,
    });
  };
}

/**
 * 可选: Bearer token 解析辅助 (供路由按需使用)
 */
function extractBearerToken(req) {
  const auth = req.headers['authorization'] || '';
  const match = auth.match(/^Bearer\s+(.+)$/i);
  return match ? match[1] : null;
}

module.exports = {
  createAuthMiddleware,
  extractBearerToken,
};
