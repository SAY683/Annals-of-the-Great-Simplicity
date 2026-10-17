# 12 · 安全边界：本地、隧道与鉴权

## 1. 默认只启动本地服务

`start_all.ps1` **默认不启动 Cloudflare 隧道**，只启动：

- `edm-takens-web`：后端 `127.0.0.1:8000`，前端 `127.0.0.1:5173`
- `trace-engine-web`：`127.0.0.1:3000-3020`
- `trace-to-edm`：`127.0.0.1:3100`

本地服务绑定回环地址，不需要 API Key；这是开发/单机研究模式。

## 2. 显式开启隧道

```powershell
.\start_all.ps1 -EnableTunnel
# 或
.\start_all.bat tunnel
```

开启后：

1. 生成随机 `TUNNEL_ACCESS_TOKEN`（可用 `-TunnelAccessToken` 指定）。
2. 在 3300/3301/3302 启动本地鉴权网关 `shared/tunnel_gate.js`。
3. `cloudflared` 指向网关，而不是直接指向 3000/3100/5173。
4. 外部访问必须先带 `?token=...` 或通过网关登录页，之后使用 HttpOnly Cookie。
5. 未携带有效令牌的请求返回 401，不进入后端。
6. 用户自定义 `TUNNEL_ACCESS_TOKEN` 必须至少 32 字符；过短令牌会被启动脚本拒绝。
7. 登录后 `next` 只允许站内绝对路径，拒绝 `https://...`、`//host` 和含换行的开放重定向。

> 注意：quick tunnel URL 本身不是鉴权；不要把裸 URL 当作访问控制。

## 3. API Key（可选的生产/反代模式）

若你使用自己的反向代理而不是网关，可设置：

| 变量 | 服务 | 作用 |
|---|---|---|
| `TRACE_API_KEY` | trace-engine-web | 普通 API/MCP 鉴权 |
| `TRACE_ADMIN_KEY` | trace-engine-web | 管理员清理/删除操作 |
| `CROSS_PROJECT_API_KEY` | trace-to-edm | 跨项目 API 鉴权 |
| `EDM_API_KEY` | edm-takens-web | EDM API 鉴权 |

未设置 `TRACE_API_KEY` 时 `trace-engine-web` 会走开发模式放行；因此**公网暴露必须使用网关或设置 key**。

## 4. 不要仅凭 `req.ip` 判断内网

cloudflared 从本机连入时，后端看到的 `req.ip` 也是 `127.0.0.1`。因此：

- `trace-to-edm` 的“回环放行”不能单独作为隧道鉴权；
- `edm-takens-web` 的 `X-Forwarded-For` 首段可被客户端伪造；
- 正确做法是网关/受信任代理 + 明确的 token/key，或 Cloudflare Access。

## 5. 网关测试

```powershell
# 未带 token：应返回 401 登录页
curl.exe -i http://127.0.0.1:3300/

# 带 token：应 302 并设置 Cookie
curl.exe -i "http://127.0.0.1:3300/?token=YOUR_TOKEN"

# 健康检查：无需 token
curl.exe http://127.0.0.1:3300/__gate/health
```

## 6. 运行时产物

`tunnel_url.txt`、`tunnel_token.txt`、`tunnel_logs/`、`work/`、`jobs.sqlite`、`__pycache__/` 均已被 `.gitignore` 排除。不要把 token 或任务输出提交到仓库。
## 7. 可信代理配置

- `edm-takens-web` 默认**不信任** `X-Forwarded-For` / `CF-Connecting-IP`，只使用 socket 对端地址。
- 只有在明确知道前置代理可信时，才设置 `EDM_TRUST_PROXY=1`；否则客户端可以伪造 `X-Forwarded-For: 127.0.0.1` 绕过本地判断。
- `tunnel_gate.js` 会向后端注入 `X-Complement-Gate: 1`；三个后端的回环放行逻辑都要求“无代理头”或“来自网关”才放行。
- 若直接使用自己的反向代理，请同时设置 `TRACE_API_KEY` / `CROSS_PROJECT_API_KEY` / `EDM_API_KEY`，不要只依赖回环地址。