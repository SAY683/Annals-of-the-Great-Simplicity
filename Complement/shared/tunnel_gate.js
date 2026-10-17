'use strict';
/**
 * tunnel_gate.js - local authentication gate in front of Cloudflare quick tunnels.
 *
 * The public quick-tunnel URL is not authentication. This gate listens only on
 * 127.0.0.1; cloudflared points at the gate. External requests must first present
 * TUNNEL_ACCESS_TOKEN (?token=... or the login form), then use an HttpOnly cookie.
 * Backend services stay bound to 127.0.0.1 and are never exposed directly.
 */
const http = require('http');
const https = require('https');
const { URL } = require('url');
const querystring = require('querystring');
const crypto = require('crypto');
const { safeNextPath, parseCookies } = require('./gate_helpers');

const TARGET = process.env.TUNNEL_TARGET || '';
const PORT = parseInt(process.env.TUNNEL_GATE_PORT || '3300', 10);
const TOKEN = process.env.TUNNEL_ACCESS_TOKEN || '';
const COOKIE_NAME = 'complement_tunnel';
const MAX_LOGIN_BODY = 16 * 1024;

if (!TARGET || !TOKEN) {
  console.error('[gate] TUNNEL_TARGET and TUNNEL_ACCESS_TOKEN are required');
  process.exit(2);
}

let target;
try {
  target = new URL(TARGET);
} catch (err) {
  console.error(`[gate] invalid TUNNEL_TARGET: ${TARGET}`);
  process.exit(2);
}
if (!['http:', 'https:'].includes(target.protocol)) {
  console.error('[gate] TUNNEL_TARGET must be http(s)');
  process.exit(2);
}

function tokenDigest(value) {
  return crypto.createHash('sha256').update(String(value || ''), 'utf8').digest();
}
const TOKEN_DIGEST = tokenDigest(TOKEN);

function safeEqual(value) {
  if (!value) return false;
  return crypto.timingSafeEqual(tokenDigest(value), TOKEN_DIGEST);
}

function requestToken(req, url) {
  const cookies = parseCookies(req.headers.cookie);
  if (cookies[COOKIE_NAME] && safeEqual(cookies[COOKIE_NAME])) return cookies[COOKIE_NAME];
  const auth = req.headers.authorization || '';
  const m = auth.match(/^Bearer\s+(.+)$/i);
  if (m && safeEqual(m[1].trim())) return m[1].trim();
  const header = req.headers['x-complement-token'];
  if (header && safeEqual(String(header).trim())) return String(header).trim();
  return null;
}

function cookieHeader(req) {
  const secure = req.headers['x-forwarded-proto'] === 'https' || req.socket.encrypted;
  return `${COOKIE_NAME}=${encodeURIComponent(TOKEN)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${secure ? '; Secure' : ''}`;
}

function loginPage(message) {
  const msg = message ? `<p class="err">${message}</p>` : '';
  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Complement Tunnel Gate</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d10;color:#d8e0ea;font:14px/1.6 system-ui,"Segoe UI",sans-serif}
.card{width:min(92vw,420px);padding:28px;border:1px solid #2a3440;border-radius:14px;background:#11161c;box-shadow:0 18px 60px rgba(0,0,0,.45)}
h1{margin:0 0 8px;font-size:18px;color:#7fd7ff;letter-spacing:.04em}
p{color:#9fb0c3}.err{color:#ff9b9b}
input{width:100%;box-sizing:border-box;margin:12px 0;padding:11px 12px;border-radius:8px;border:1px solid #344251;background:#0b0f14;color:#e8f0f8}
button{width:100%;padding:11px;border:0;border-radius:8px;background:#1f8fce;color:#fff;font-weight:600;cursor:pointer}
button:hover{background:#27a6ec}code{color:#b7e5ff}
</style></head><body><main class="card">
<h1>Complement · Tunnel Gate</h1>
<p>This local research service is protected. Enter the tunnel access token.</p>
${msg}
<form method="post" action="/__gate/login">
  <input name="token" type="password" autocomplete="current-password" placeholder="Tunnel access token" autofocus>
  <input type="hidden" name="next" value="/">
  <button type="submit">Enter</button>
</form>
<p>The token is generated and printed by <code>start_all.ps1 -EnableTunnel</code>.</p>
</main></body></html>`;
}

function sendLogin(res, status = 401, message = '') {
  res.writeHead(status, {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(loginPage(message));
}

function proxy(req, res, url) {
  const headers = { ...req.headers };
  headers.host = target.host;
  headers['x-forwarded-host'] = req.headers.host || '';
  headers['x-forwarded-proto'] = req.headers['x-forwarded-proto'] || 'https';
  headers['x-real-ip'] = req.headers['cf-connecting-ip'] || req.headers['x-real-ip'] || req.socket.remoteAddress || '';
  headers['x-complement-gate'] = '1';

  const transport = target.protocol === 'https:' ? https : http;
  const upstreamUrl = new URL(url.pathname + url.search, target.origin);
  upstreamUrl.searchParams.delete('token');
  const proxyReq = transport.request({
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port || (target.protocol === 'https:' ? 443 : 80),
    method: req.method,
    path: upstreamUrl.pathname + upstreamUrl.search,
    headers,
  }, proxyRes => {
    res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', err => {
    console.error(`[gate] upstream error: ${err.message}`);
    if (!res.headersSent) {
      res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
    }
    res.end(JSON.stringify({ error: 'TUNNEL_UPSTREAM_ERROR', message: err.message }));
  });

  req.pipe(proxyReq);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (url.pathname === '/__gate/health') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(JSON.stringify({ ok: true, service: 'complement-tunnel-gate', target: target.origin }));
    return;
  }

  if (url.pathname === '/__gate/login' && req.method === 'POST') {
    let body = '';
    req.setEncoding('utf8');
    req.on('data', chunk => {
      body += chunk;
      if (body.length > MAX_LOGIN_BODY) {
        body = '';
        req.destroy();
      }
    });
    req.on('end', () => {
      const form = querystring.parse(body || '');
      if (safeEqual(String(form.token || ''))) {
        res.writeHead(302, {
          'Set-Cookie': cookieHeader(req),
          'Location': safeNextPath(form.next),
          'Cache-Control': 'no-store',
        });
        res.end();
      } else {
        sendLogin(res, 401, 'Invalid token.');
      }
    });
    return;
  }

  const token = requestToken(req, url);
  if (!token) {
    const q = url.searchParams.get('token');
    if (q && safeEqual(q)) {
      const clean = new URL(url.pathname, `http://${req.headers.host || 'localhost'}`);
      clean.search = url.search;
      clean.searchParams.delete('token');
      res.writeHead(302, {
        'Set-Cookie': cookieHeader(req),
        'Location': clean.pathname + (clean.search || ''),
        'Cache-Control': 'no-store',
      });
      res.end();
      return;
    }
    sendLogin(res, 401);
    return;
  }

  proxy(req, res, url);
});

server.on('upgrade', (req, socket, head) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const upgradeToken = url.searchParams.get('token');
  const upstreamToken = new URL(url.pathname + url.search, target.origin);
  upstreamToken.searchParams.delete('token');
  if (!requestToken(req, url) && !(upgradeToken && safeEqual(upgradeToken))) {
    socket.write('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');
    socket.destroy();
    return;
  }
  const headers = { ...req.headers, host: target.host };
  const transport = target.protocol === 'https:' ? https : http;
  const upstream = transport.request({
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port || (target.protocol === 'https:' ? 443 : 80),
    method: req.method,
    path: upstreamToken.pathname + upstreamToken.search,
    headers,
  });
  upstream.on('upgrade', (proxyRes, proxySocket, proxyHead) => {
    socket.write('HTTP/1.1 101 Switching Protocols\r\n');
    Object.entries(proxyRes.headers).forEach(([k, v]) => socket.write(`${k}: ${v}\r\n`));
    socket.write('\r\n');
    if (proxyHead && proxyHead.length) socket.write(proxyHead);
    proxySocket.pipe(socket);
    socket.pipe(proxySocket);
  });
  upstream.on('error', () => socket.destroy());
  upstream.end();
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[gate] listening on http://127.0.0.1:${PORT} -> ${target.origin}`);
});
