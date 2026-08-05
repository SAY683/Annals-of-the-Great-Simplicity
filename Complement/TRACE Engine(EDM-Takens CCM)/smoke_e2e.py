#!/usr/bin/env python3
"""
smoke_e2e.py — 便携目录端到端冒烟测试 (ROUND51)
============================================
真实启动三个 Web 服务, 跑通 文本→TRACE→trace-to-edm→EDM 全链路, 并对结果做断言.

把 verify_portable.py 从"查文件存在"升级为"查行为正确"的关键一环:
不启动服务时所有的 15 项契约都只能证明"文件在", 本脚本证明"链路真的能跑".

链路 (全走 HTTP, 真实服务):
  1. 启动 edm-takens-web  (FastAPI)    — EDM 分析服务
  2. 启动 trace-engine-web (Node+Koa)  — TRACE 前端服务
  3. 启动 trace-to-edm    (Node+Express) — 桥接服务 (编排链路)
  4. 三服务 /api/health 全绿
  5. trace-engine-web /api/config 契约 (SUPER 模式 + max_segments)
  6. 文本→数据集: trace-to-edm /api/dataset/add-text 喂入 15 条文本
  7. TRACE→轨迹: trace-to-edm /api/pipeline/run 批量 TRACE 分析 → 轨迹 CSV
       断言: SSE done 事件 success=true, trajectory_rows>=15, edm_ready=true
       断言: 轨迹 CSV 含 trace_status/trace_error/trace_mode 列, 至少 1 行非失败
  8. 轨迹→EDM: trace-to-edm /api/edm/trigger (target=z_pca_1) → EDM job
  9. 轮询:     trace-to-edm /api/edm/poll/:jobId 至完成
  10. 断言: EDM job 完成且结果含 4 个科研披露字段
       (is_strict_confirmatory / methodology_disclaimer / effective_lib_sizes / out_of_sample_used)

隔离性 (不污染便携目录, 所有运行时写入重定向到 %TEMP%/smoke_e2e_<pid>/):
  - edm-takens-web:  EDM_PORT + EDMTAKENS_DATA_DIR/RESULTS_DIR/ARCHIVE_DIR/WORKDIR + JOBS_DB
  - trace-to-edm:    TRACE_TO_EDM_PROJECTS_DIR/OUTPUTS_DIR/LOG_FILE + EDM_API_URL + EDM_DATA_DIR
  - trace-engine-web: PORT + TRACE_WORK_DIR + TRACE_ENGINE_SKILL_DIR
  - 全部子进程 PYTHONDONTWRITEBYTECODE=1 (防 __pycache__ 污染)

退出码:
  0 = 全链路通过
  1 = 失败 (服务启动失败 / 断言失败 / 超时)
  2 = SKIP (node/npm/依赖缺失, 环境不支持, 不算失败)

用法:
  python smoke_e2e.py [--verbose] [--timeout-min N] [--texts N]
"""
import os
import sys

# 在任何项目模块导入之前禁止 __pycache__ 写入 (便携目录无运行时产物约束)
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

# ROUND51: UTF-8 输出, 避免 GBK 控制台/verify 子进程捕获时中文乱码
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import argparse
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ── 配置 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # 便携成品根 (TRACE Engine(EDM-Takens CCM)/)
EDM_WEB_DIR = SCRIPT_DIR / "edm-takens-web"
TRACE_ENGINE_DIR = SCRIPT_DIR / "trace-engine"
TRACE_WEB_DIR = SCRIPT_DIR / "trace-engine-web"
TRACE_TO_EDM_DIR = SCRIPT_DIR / "trace-to-edm"

EDM_MIN_ROWS = 15           # 与 server.js / edm_trigger.EDM_MIN_ROWS_FOR_ANALYSIS 对齐
DISCLOSURE_FIELDS = [
    "is_strict_confirmatory",
    "methodology_disclaimer",
    "effective_lib_sizes",
    "out_of_sample_used",
]

# 15 条示例文本: 信息茧房 / 算法推荐 / 舆论极化 主题, 短句保证 LIGHT 模式快速
SAMPLE_TEXTS = [
    "算法推荐系统通过持续分析用户行为强化了信息茧房效应",
    "社交媒体平台的反馈机制加剧了群体极化的现象",
    "新闻聚合工具根据点击历史推送相似观点降低认知多样性",
    "公共讨论空间中的立场对立与算法分流存在因果关系",
    "碎片化阅读习惯改变了公众对复杂议题的注意力分配",
    "舆论场中的情绪传播速度远超事实核实的传播速度",
    "信息生态系统的封闭性会削弱社会共识的形成基础",
    "内容审核机制的透明度直接影响用户对平台信任度",
    "跨平台信息流动促进了不同群体之间的观点交流",
    "数字素养差异导致不同人群对虚假信息的抵御能力不同",
    "平台推荐算法的商业目标与公共信息质量目标存在冲突",
    "大规模舆论事件中信息源多样性与事件走向密切相关",
    "长期暴露于单一立场内容会降低个体对异见的容忍度",
    "公共政策讨论中的事实基础被情绪动员逐步侵蚀",
    "健康的信息生态需要算法透明与用户自主选择的平衡",
]

# 测试文本数量 (可 --texts 覆盖; EDM 需要 >=15 行)
DEFAULT_TEXTS = 15

VERBOSE = False


def log(msg: str, level: str = "  "):
    print(f"[{level}] {msg}", flush=True)


def dbg(msg: str):
    if VERBOSE:
        print(f"    {msg}", flush=True)


# ── 端口 / HTTP 工具 ──────────────────────────────────────
def find_free_port(start: int, end: int) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"端口范围 {start}-{end} 无空闲端口")


def _opener():
    # 强制直连, 避免环境中的 HTTP_PROXY/HTTPS_PROXY 拦截本地请求
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_json(base: str, method: str, path: str, data=None, timeout: int = 30, as_json: bool = False):
    """HTTP 请求, 返回 (status, json_dict|None, raw_text|None)。连接失败返回 (None, None, None)。

    as_json=True 时以 application/json 发送 (如 add-text 需要 JSON 数组 body);
    否则 dict 数据以 application/x-www-form-urlencoded 发送。
    """
    url = f"{base}{path}"
    body = None
    headers = {}
    if data is not None:
        if isinstance(data, dict) and not as_json:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return e.code, json.loads(raw) if raw else None, raw
        except json.JSONDecodeError:
            return e.code, None, raw
    except (urllib.error.URLError, ConnectionError, OSError):
        return None, None, None


def wait_health(base: str, path: str, timeout: float, name: str) -> bool:
    """轮询健康检查直到 200 或超时。"""
    deadline = time.time() + timeout
    last = "无响应"
    while time.time() < deadline:
        status, data, raw = http_json(base, "GET", path, timeout=5)
        if status == 200 and data is not None:
            ok = data.get("success") is True or data.get("status") in ("healthy", "degraded", "ok")
            if ok:
                log(f"{name} 健康检查通过 (port={base.split(':')[-1]})")
                return True
            last = str(data)[:120]
        elif status == 200:
            last = raw[:120]
        else:
            last = f"status={status} {str(raw)[:120]}"
        time.sleep(0.5)
    log(f"{name} 未在 {timeout:.0f}s 内就绪: {last}", "FAIL")
    return False


# ── SSE 解析 ──────────────────────────────────────────────
def post_sse(base: str, path: str, data: dict, timeout: float):
    """POST 一个 SSE 端点, 逐事件收集, 直到 done/error 事件或超时。

    Returns: (success, events: list[dict], error_msg)
    """
    url = f"{base}{path}"
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    events = []
    deadline = time.time() + timeout
    try:
        with _opener().open(req, timeout=timeout) as resp:
            event_name = None
            data_lines = []
            for raw_line in resp:
                if time.time() > deadline:
                    return False, events, "SSE 超时"
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
                elif line == "":
                    if event_name or data_lines:
                        payload = "\n".join(data_lines)
                        try:
                            parsed = json.loads(payload)
                        except json.JSONDecodeError:
                            parsed = {"raw": payload}
                        events.append({"event": event_name or "message", "data": parsed})
                        if event_name in ("done", "error"):
                            return (event_name == "done"), events, None
                        event_name = None
                        data_lines = []
    except Exception as e:
        return False, events, f"SSE 请求异常: {e}"
    return False, events, "SSE 未收到 done/error 事件 (连接关闭)"


# ── 服务启动 / 清理 ───────────────────────────────────────
class Service:
    def __init__(self, name, proc, port, log_path: Path):
        self.name = name
        self.proc = proc
        self.port = port
        self.log_path = log_path


def _service_log_file(work_root: Path, name: str) -> Path:
    """服务日志文件路径 (输出重定向到文件而非 PIPE, 避免 pipe 缓冲填满阻塞)."""
    path = work_root / f"{name}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def start_edm_backend(env: dict, work_root: Path) -> Service:
    """启动 edm-takens-web 后端 (FastAPI)。

    输出重定向到文件而非 PIPE: EDM 分析打印大量输出 (tqdm/警告/日志),
    PIPE 缓冲 (约 64KB) 填满后 Python 写 stdout 会被阻塞, 导致整个进程
    冻结 → HTTP 无响应 (socket hang up / health 超时). 这是 smoke 首轮
    EDM job 卡死的根因.
    """
    port = find_free_port(8400, 8500)
    e = os.environ.copy()
    e.update(env)
    e["EDM_PORT"] = str(port)
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    log_path = _service_log_file(work_root, "edm-takens-web")
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, "run_backend.py"],
        cwd=str(EDM_WEB_DIR),
        env=e,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return Service("edm-takens-web", proc, port, log_path)


def start_node_service(name, work_dir: Path, port: int, env: dict, work_root: Path) -> Service:
    """启动 Node.js 服务 (trace-engine-web / trace-to-edm), 输出重定向到文件。"""
    e = os.environ.copy()
    e.update(env)
    e["PORT"] = str(port)
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    log_path = _service_log_file(work_root, name)
    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        ["node", "server.js"],
        cwd=str(work_dir),
        env=e,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return Service(name, proc, port, log_path)


def ensure_node_deps(work_dir: Path, name: str) -> bool:
    """确保 Node 服务依赖已安装。缺失时尝试 npm install; 失败返回 False (→SKIP)。"""
    if (work_dir / "node_modules").exists():
        return True
    npm = shutil.which("npm")
    if not npm:
        return False
    log(f"{name}: node_modules 缺失, 执行 npm install (可能耗时)...")
    proc = subprocess.run(
        [npm, "install", "--no-audit", "--no-fund"],
        cwd=str(work_dir),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.returncode == 0 and (work_dir / "node_modules").exists()


def drain_process(svc: Service) -> str:
    """从服务日志文件读取尾部 (stdout/stderr 已重定向到文件)。"""
    if svc.log_path and svc.log_path.exists():
        try:
            return svc.log_path.read_text(encoding="utf-8", errors="replace")[-1500:]
        except Exception:
            return ""
    return ""


def terminate_services(services: list):
    for svc in services:
        try:
            svc.proc.terminate()
        except Exception:
            pass
    # 等待优雅退出, 超时后强杀
    deadline = time.time() + 8
    for svc in services:
        while time.time() < deadline and svc.proc.poll() is None:
            time.sleep(0.2)
        if svc.proc.poll() is None:
            try:
                svc.proc.kill()
            except Exception:
                pass
    for svc in services:
        try:
            svc.proc.wait(timeout=3)
        except Exception:
            pass


def collect_service_logs(services: list) -> dict:
    """收集各服务日志文件尾部, 用于失败诊断。"""
    logs = {}
    for svc in services:
        tail = drain_process(svc)
        status = f"exit={svc.proc.poll()}" if svc.proc.poll() is not None else "still-running"
        logs[svc.name] = f"({status}) {tail}" if tail else f"({status}) (no output)"
    return logs


# ── 断言工具 ──────────────────────────────────────────────
class Check:
    def __init__(self, name):
        self.name = name
        self.failed = False
        self.messages = []

    def ok(self, msg):
        self.messages.append(f"  [PASS] {msg}")

    def bad(self, msg):
        self.failed = True
        self.messages.append(f"  [FAIL] {msg}")

    def require(self, cond, ok_msg, fail_msg):
        if cond:
            self.ok(ok_msg)
        else:
            self.bad(fail_msg)

    def finish(self) -> bool:
        print(f"[{'PASS' if not self.failed else 'FAIL'}] {self.name}")
        for m in self.messages:
            print(m)
        return not self.failed


def json_has_keys(obj, keys) -> list:
    """递归在 JSON 对象中查找键, 返回缺失键列表 (DFS 栈式, 键名出现在任意深度即算找到)。"""
    target = set(keys)
    found = set()
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            found |= (target & set(node.keys()))
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
        if found == target:
            break
    return sorted(target - found)


# ── 主流程 ────────────────────────────────────────────────
def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description="便携目录 E2E 全链路冒烟测试")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    parser.add_argument("--keep", action="store_true", help="失败时保留临时目录 (调试用)")
    parser.add_argument("--timeout-min", type=float, default=12.0, help="整链超时 (分钟)")
    parser.add_argument("--texts", type=int, default=DEFAULT_TEXTS, help=f"测试文本数 (默认 {DEFAULT_TEXTS})")
    args = parser.parse_args()
    VERBOSE = args.verbose
    keep_workdir = args.keep
    n_texts = max(args.texts, EDM_MIN_ROWS)
    chain_timeout = args.timeout_min * 60.0

    print("=" * 70)
    print("便携目录 E2E 全链路冒烟测试 (smoke_e2e)")
    print(f"目录: {SCRIPT_DIR}")
    print(f"文本数: {n_texts} | 总超时: {chain_timeout:.0f}s")
    print("=" * 70)

    # ── 前置检查: 目录 + node/npm ──────────────────────────
    pre = Check("前置依赖")
    missing = [d for d in [EDM_WEB_DIR, TRACE_WEB_DIR, TRACE_TO_EDM_DIR, TRACE_ENGINE_DIR] if not d.exists()]
    pre.require(not missing, "四大项目目录齐全", f"缺失目录: {missing}")
    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        print("[SKIP] 全链路冒烟")
        print("  前置依赖缺失: node/npm 不在 PATH 中, 无法启动 Node 服务")
        print("  (环境限制, 非便携目录缺陷; verify_portable 同规则视为 SKIP)")
        return 2
    pre.require(bool(node) and bool(npm), "node/npm 可用", "node/npm 缺失")
    if not pre.finish():
        return 1

    # ── 隔离工作目录 ───────────────────────────────────────
    work_root = Path(tempfile.gettempdir()) / f"smoke_e2e_{os.getpid()}"
    edm_data = work_root / "edm_data"
    edm_results = work_root / "edm_results"
    edm_archive = work_root / "edm_archive"
    edm_workdir = work_root / "edm_workdir"
    edm_jobs = work_root / "edm_jobs.sqlite"
    t2e_projects = work_root / "t2e_projects"
    t2e_outputs = work_root / "t2e_outputs"
    t2e_log = work_root / "t2e_server.log"
    trace_work = work_root / "trace_work"
    for d in [work_root, edm_data, edm_results, edm_archive, edm_workdir, t2e_projects, t2e_outputs, trace_work]:
        d.mkdir(parents=True, exist_ok=True)
    # 预置 EDM 数据目录: 复制便携目录 data/ 的既有 CSV (game_log.csv 等).
    # 否则 sniff_environment 的 files_all_ok=False (data_path('game_log.csv')
    # 不存在) → pipeline 返回 environment_not_ready, EDM 分析不会真正运行.
    _src_data = EDM_WEB_DIR / "data"
    if _src_data.exists():
        _copied = 0
        for _f in _src_data.iterdir():
            if _f.is_file():
                shutil.copy2(_f, edm_data / _f.name)
                _copied += 1
        log(f"预置 EDM 数据目录: {_copied} 个 CSV (from {_src_data.name}/)")
    log(f"隔离工作目录: {work_root}")

    services = []
    try:
        # ── 启动 edm-takens-web ─────────────────────────────
        log("启动 edm-takens-web (FastAPI)...")
        edm_svc = start_edm_backend({
            "EDMTAKENS_DATA_DIR": str(edm_data),
            "EDMTAKENS_RESULTS_DIR": str(edm_results),
            "EDMTAKENS_ARCHIVE_DIR": str(edm_archive),
            "EDMTAKENS_WORKDIR": str(edm_workdir),
            "JOBS_DB": str(edm_jobs),
        }, work_root)
        services.append(edm_svc)
        edm_base = f"http://127.0.0.1:{edm_svc.port}"
        if not wait_health(edm_base, "/api/health", 120, "edm-takens-web"):
            raise RuntimeError("edm-takens-web 启动失败")

        # ── 启动 trace-engine-web ───────────────────────────
        if not ensure_node_deps(TRACE_WEB_DIR, "trace-engine-web"):
            print("[SKIP] 全链路冒烟")
            print("  trace-engine-web 依赖安装失败 (npm 不可用或 install 失败), 无法启动服务")
            return 2
        log("启动 trace-engine-web (Node+Koa)...")
        tew_svc = start_node_service(
            "trace-engine-web", TRACE_WEB_DIR, find_free_port(3400, 3500), {
                "TRACE_WORK_DIR": str(trace_work),
                "TRACE_ENGINE_SKILL_DIR": str(TRACE_ENGINE_DIR / "examples" / "counterfactual_hybrid"),
            }, work_root
        )
        services.append(tew_svc)
        tew_base = f"http://127.0.0.1:{tew_svc.port}"
        if not wait_health(tew_base, "/api/health", 90, "trace-engine-web"):
            raise RuntimeError("trace-engine-web 启动失败")

        # ── 启动 trace-to-edm ───────────────────────────────
        if not ensure_node_deps(TRACE_TO_EDM_DIR, "trace-to-edm"):
            print("[SKIP] 全链路冒烟")
            print("  trace-to-edm 依赖安装失败 (npm 不可用或 install 失败), 无法启动服务")
            return 2
        log("启动 trace-to-edm (Node+Express)...")
        t2e_svc = start_node_service(
            "trace-to-edm", TRACE_TO_EDM_DIR, find_free_port(3500, 3600), {
                "EDM_API_URL": edm_base,
                "EDM_DATA_DIR": str(edm_data),          # 复制轨迹 CSV 到 EDM 临时数据目录
                "TRACE_TO_EDM_PROJECTS_DIR": str(t2e_projects),
                "TRACE_TO_EDM_OUTPUTS_DIR": str(t2e_outputs),
                "TRACE_TO_EDM_LOG_FILE": str(t2e_log),
                # bridge.py 的 TRACE 任务输出 (config.TRACE_WORK_DIR 现读此变量):
                # 指向临时目录, 防止每次 TRACE 分析把 task 输出写进便携
                # trace-engine-web/work/outputs 造成污染.
                "TRACE_WORK_DIR": str(trace_work),
            }, work_root
        )
        services.append(t2e_svc)
        t2e_base = f"http://127.0.0.1:{t2e_svc.port}"
        if not wait_health(t2e_base, "/api/health", 60, "trace-to-edm"):
            raise RuntimeError("trace-to-edm 启动失败")

        # ── 契约 1: 三服务健康 + trace-engine-web /api/config ──
        health = Check("三服务健康 + trace-engine-web /api/config")
        for name, base in [("edm-takens-web", edm_base), ("trace-engine-web", tew_base), ("trace-to-edm", t2e_base)]:
            status, data, _ = http_json(base, "GET", "/api/health")
            health.require(status == 200, f"{name} /api/health 200", f"{name} /api/health status={status}")
        status, cfg, _ = http_json(tew_base, "GET", "/api/config")
        health.require(status == 200, "/api/config 200", f"/api/config status={status}")
        if status == 200 and cfg:
            modes = cfg.get("modes") or {}
            schema = cfg.get("bridgeParamSchema") or {}
            health.require("super" in modes, "SUPER 模式已暴露", "modes 缺 super")
            health.require("max_segments" in schema, "bridgeParamSchema.max_segments 存在", "缺 max_segments")
        if not health.finish():
            raise RuntimeError("健康/契约检查失败")

        # ── 阶段 A: 文本 → 数据集 ────────────────────────────
        texts = SAMPLE_TEXTS[:n_texts]
        while len(texts) < n_texts:
            texts.append(texts[len(texts) % len(SAMPLE_TEXTS)])
        rows = [
            {"timestamp": f"2026-08-05 09:{i:02d}", "text": t, "source": "smoke_e2e"}
            for i, t in enumerate(texts)
        ]
        log(f"喂入 {len(rows)} 条文本到 trace-to-edm 数据集...")
        # 注意: add-text 需要 JSON body (express.json 解析), urlencoded 会把
        # texts 变成字符串, Python 端逐字符迭代崩溃且无 error 字段返回.
        status, add_result, raw = http_json(t2e_base, "POST", "/api/dataset/add-text",
                                            {"texts": rows}, as_json=True, timeout=30)
        if status != 200:
            raise RuntimeError(f"/api/dataset/add-text HTTP {status}: {raw[:200]}")
        if isinstance(add_result, dict) and add_result.get("error"):
            raise RuntimeError(f"/api/dataset/add-text 失败: {add_result}")
        added = add_result if isinstance(add_result, int) else (add_result.get("added") if isinstance(add_result, dict) else None)
        dbg(f"add-text 返回: {add_result}")
        if added is not None:
            log(f"数据集已添加 {added} 条文本 (pending)")
        else:
            log(f"数据集添加完成 (返回: {add_result})")

        # ── 阶段 B: TRACE 批量分析 → 轨迹 CSV ───────────────
        log("运行 /api/pipeline/run (批量 TRACE 分析)...")
        ok, events, err = post_sse(t2e_base, "/api/pipeline/run", {"trace_mode": "light"}, timeout=chain_timeout * 0.5)
        for ev in events:
            d = ev["data"]
            if ev["event"] == "log":
                dbg(f"SSE log: {d.get('message', d)}")
            elif ev["event"] == "progress":
                dbg(f"SSE progress: {d.get('message', d)}")
            elif ev["event"] == "warn":
                log(f"SSE warn: {d.get('message', d)}", "WARN")
            elif ev["event"] == "done":
                dbg(f"SSE done: {d}")
            elif ev["event"] == "error":
                log(f"SSE error: {d}", "ERROR")
        done_events = [e for e in events if e["event"] in ("done", "error")]
        done = done_events[-1] if done_events else None
        if done is None:
            raise RuntimeError(f"/api/pipeline/run 未收到 done 事件: {err or events[-5:] if events else '无事件'}")

        pipe = Check("阶段 B: TRACE→轨迹 CSV")
        if done["event"] == "error":
            pipe.bad(f"pipeline error: {done['data']}")
        else:
            d = done["data"]
            pipe.require(d.get("success") is True, "pipeline done success=true", f"success={d.get('success')}")
            pipe.require(int(d.get("trajectory_rows") or 0) >= EDM_MIN_ROWS,
                         f"trajectory_rows={d.get('trajectory_rows')} >= {EDM_MIN_ROWS}",
                         f"trajectory_rows={d.get('trajectory_rows')} < {EDM_MIN_ROWS}")
            pipe.require(d.get("edm_ready") is True, "edm_ready=true", f"edm_ready={d.get('edm_ready')}")
        if not pipe.finish():
            raise RuntimeError("TRACE 阶段断言失败")

        # ── 阶段 B': 轨迹 CSV 列契约 (独立于 SSE 验证) ───────
        traj_csv = t2e_projects / "default" / "narrative_meta_trajectories.csv"
        csv_check = Check("阶段 B': 轨迹 CSV 列契约")
        if not traj_csv.exists():
            csv_check.bad(f"轨迹 CSV 不存在: {traj_csv}")
        else:
            import csv as _csv
            with open(traj_csv, "r", encoding="utf-8", newline="") as f:
                reader = list(_csv.DictReader(f))
            headers = list(reader[0].keys()) if reader else []
            for col in ["trace_status", "trace_error", "trace_mode"]:
                csv_check.require(col in headers, f"列 {col} 存在", f"列 {col} 缺失")
            n_ok = sum(1 for r in reader if r.get("trace_status") in ("OK", "PARTIAL"))
            csv_check.require(n_ok >= 1, f"{n_ok}/{len(reader)} 行 trace_status=OK/PARTIAL", "无成功行 (trace_status 全失败)")
            csv_check.require(len(reader) >= EDM_MIN_ROWS, f"轨迹行数 {len(reader)} >= {EDM_MIN_ROWS}", f"行数不足: {len(reader)}")
        if not csv_check.finish():
            raise RuntimeError("轨迹 CSV 契约断言失败")

        # ── 阶段 C: 触发 EDM 分析 ────────────────────────────
        log("触发 EDM 分析 (/api/edm/trigger)...")
        # 目标: z_pca_1 (L2 世俗语义主轴, LIGHT 模式下保证有方差;
        # ate 在 LIGHT 模式下多行为 0, 不适合作为 EDM 目标)
        status, trig, raw = http_json(t2e_base, "POST", "/api/edm/trigger",
                                      {"target": "z_pca_1", "q": 3}, timeout=60)
        if status != 200 or not trig:
            raise RuntimeError(f"/api/edm/trigger 失败: status={status} raw={raw[:200]}")
        job_id = trig.get("job_id")
        if not job_id:
            raise RuntimeError(f"/api/edm/trigger 未返回 job_id: {trig}")
        log(f"EDM job_id={job_id} status={trig.get('status')}")

        # ── 阶段 D: 轮询 EDM job 至完成 ──────────────────────
        # EDM 分析 (含 IAAFT 替代检验/CCM/HAVOK) 在小样本上可能耗时数分钟,
        # 给足预算: 总超时的 55%
        edm_poll_timeout = chain_timeout * 0.55
        log(f"轮询 EDM job ({edm_poll_timeout:.0f}s 上限)...")
        final = None
        deadline = time.time() + edm_poll_timeout
        last_status = "pending"
        n_polls = 0
        while time.time() < deadline:
            status, data, _ = http_json(t2e_base, "GET", f"/api/edm/poll/{job_id}", timeout=15)
            if status == 200 and data:
                last_status = data.get("status", "unknown")
                n_polls += 1
                if n_polls % 10 == 0:  # 每 ~30s 报告一次进度
                    dbg(f"EDM job {last_status} (logs={data.get('log_count')}, {int(time.time()-deadline+edm_poll_timeout)}s)")
                if last_status in ("done", "completed"):
                    final = data
                    break
                if last_status in ("error", "failed"):
                    final = data
                    break
            time.sleep(3)
        if final is None:
            raise RuntimeError(f"EDM job 超时未完成 (最后状态: {last_status})")

        edm_check = Check("阶段 C+D: EDM 分析")
        final_status = final.get("status")
        edm_check.require(final_status in ("done", "completed"),
                          f"EDM job 完成 (status={final_status})",
                          f"EDM job 失败 (status={final_status}, error={str(final.get('error'))[:200]})")
        result = final.get("result") or {}
        if isinstance(result, dict):
            edm_check.require(result.get("success") is True, "result.success=true", f"result.success={result.get('success')}")
            summary = result.get("summary") or {}
            # 诊断: 若 summary 显示 pipeline 未真正运行, 直接暴露错误状态
            for _k in ("pipeline", "cross_validation", "interpretation"):
                _v = summary.get(_k)
                if isinstance(_v, str) and _v.startswith("error"):
                    edm_check.bad(f"EDM 阶段未真正运行: {_k} = {_v}")
            missing = json_has_keys(summary, DISCLOSURE_FIELDS)
            edm_check.require(not missing,
                              f"科研披露字段齐全 ({len(DISCLOSURE_FIELDS) - len(missing)}/{len(DISCLOSURE_FIELDS)})",
                              f"科研披露字段缺失: {missing}")
            if missing:
                edm_check.bad(f"summary keys: {sorted(summary.keys())}")
                edm_check.bad(f"summary.ccm 存在: {'ccm' in summary}")
            task_id = result.get("task_id")
            if task_id:
                edm_check.ok(f"task_id={task_id} images={len(result.get('images') or [])}")
        else:
            edm_check.bad(f"EDM result 非对象: {str(result)[:200]}")
        if not edm_check.finish():
            raise RuntimeError("EDM 阶段断言失败")

        # ── 全部通过 ─────────────────────────────────────────
        print("\n" + "=" * 70)
        print("E2E 全链路冒烟测试: 全部通过 ✓")
        print("  文本→TRACE→trace-to-edm→EDM 链路真实跑通")
        print("  三服务真实启动 + 健康 + 契约 + 结果披露字段断言")
        print("=" * 70)
        return 0

    except Exception as e:
        print(f"\n[FAIL] E2E 冒烟测试失败: {e}", flush=True)
        # 收集各服务日志文件尾部, 便于诊断
        for svc in services:
            tail = drain_process(svc)
            if tail.strip():
                print(f"\n--- {svc.name} (port={svc.port}) 尾部日志 ---")
                print(tail[-1200:])
            else:
                print(f"\n--- {svc.name} (port={svc.port}) 无日志输出, exit={svc.proc.poll()} ---")
        return 1

    finally:
        # ── 清理: 终止服务 + 删除临时目录 ────────────────────
        log("清理: 终止服务进程...")
        terminate_services(services)
        # 稍等进程退出, 释放端口/文件锁后再删目录
        time.sleep(0.5)
        if keep_workdir:
            log(f"调试模式: 保留临时目录 {work_root}")
        else:
            try:
                shutil.rmtree(work_root, ignore_errors=True)
                log(f"清理: 已删除临时目录 {work_root}")
            except Exception:
                log(f"清理: 临时目录 {work_root} 删除失败 (留待系统清理)")


if __name__ == "__main__":
    sys.exit(main())
