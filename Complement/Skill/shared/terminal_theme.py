"""
特摄防卫队基地 — 统一终端主题模块
====================================
为 trace-engine / edm-takens 两大 CLI 提供统一的：
- ANSI 颜色
- 日志分级图标
- 阶段指示器
- 标题框 / 裁决面板 / 数值高亮

使用方式:
    from terminal_theme import T, log_stage, log_info, log_warn, log_error, print_header, stage_bar, verdict_panel

注意: 仅做输出层包装，不引入业务逻辑。
"""

import os
import sys
from datetime import datetime


class T:
    """ANSI 颜色与样式（自动检测终端支持）"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # 部门色
    COMMAND = "\033[38;5;208m"      # 昭和橙 #ff9f43
    RELAY = "\033[38;5;220m"        # 信号黄 #f2c94c
    OBSERVATORY = "\033[38;5;49m"   # 终端绿 #00ff9d
    ANALYSIS = "\033[38;5;75m"      # 科学蓝 #4da6ff
    THEORY = "\033[38;5;183m"       # 紫 #c084fc

    # 功能色
    CYAN = "\033[38;5;51m"          # 平成青
    GREEN = "\033[38;5;82m"         # 通过
    YELLOW = "\033[38;5;220m"       # 警告
    RED = "\033[38;5;196m"          # 错误
    ORANGE = "\033[38;5;208m"       # SUPER/关键
    WHITE = "\033[38;5;255m"
    GRAY = "\033[38;5;245m"

    # 背景
    BG_DARK = "\033[48;5;232m"
    BG_PANEL = "\033[48;5;234m"


# 日志分级图标（与 Web 端统一）
ICONS = {
    "stage": "▶",
    "info": "◉",
    "warn": "▲",
    "error": "✖",
    "done": "✓",
    "key": "✦",
}


def supports_color() -> bool:
    """检测当前终端是否支持 ANSI 颜色"""
    return sys.stdout.isatty() and os.environ.get("TERM") not in (None, "dumb")


def colorize(text: str, color: str) -> str:
    """若终端支持则加色，否则原样返回"""
    return f"{color}{text}{T.RESET}" if supports_color() else text


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def print_header(title: str, dept: str = "ANALYSIS", subtitle: str = "") -> None:
    """打印特摄基地风格的标题框

    Args:
        title: 主标题
        dept:  部门名 (COMMAND/RELAY/OBSERVATORY/ANALYSIS/THEORY)
        subtitle: 副标题（可选）
    """
    dept_color = getattr(T, dept.upper(), T.ANALYSIS)
    width = 58
    now = _now()

    if not supports_color():
        # 非tty模式（如Web子进程）：使用简洁格式，不输出纯分隔线
        print(f"[{dept.upper()}] {title}")
        if subtitle:
            print(f"  {subtitle}")
        return

    dept_label = f"[{dept.upper()}]"
    print(colorize(f"╔{'═' * (width - 2)}╗", dept_color))
    print(
        colorize("║", dept_color)
        + " "
        + colorize("DEFENSE TEAM BASE TERMINAL", T.BOLD + T.WHITE)
        + "  "
        + colorize(f"MISSION CLOCK {now}", T.GRAY)
        + " " * 8
        + colorize("║", dept_color)
    )
    print(
        colorize("║", dept_color)
        + " "
        + colorize(dept_label, dept_color)
        + " "
        + colorize(title, T.WHITE)
        + " " * (width - 7 - len(dept_label) - len(title))
        + colorize("║", dept_color)
    )
    if subtitle:
        print(
            colorize("║", dept_color)
            + " "
            + colorize(subtitle, T.GRAY)
            + " " * (width - 4 - len(subtitle))
            + colorize("║", dept_color)
        )
    print(colorize(f"╚{'═' * (width - 2)}╝", dept_color))
    print()


def print_ascii_logo(lines: list[str], dept: str = "ANALYSIS") -> None:
    """打印 ASCII Logo，逐行带部门色"""
    dept_color = getattr(T, dept.upper(), T.ANALYSIS)
    for line in lines:
        print(colorize(line, dept_color))
    print()


def log_stage(msg: str) -> None:
    """阶段日志：▶ STAGE"""
    print(f"{colorize(ICONS['stage'], T.CYAN)} {colorize('STAGE', T.CYAN + T.BOLD)} {msg}")


def log_info(msg: str) -> None:
    """信息日志：◉ INFO"""
    print(f"{colorize(ICONS['info'], T.CYAN)} {colorize('INFO', T.CYAN)}  {msg}")


def log_warn(msg: str) -> None:
    """警告日志：▲ WARN"""
    print(f"{colorize(ICONS['warn'], T.YELLOW)} {colorize('WARN', T.YELLOW + T.BOLD)}  {msg}")


def log_error(msg: str) -> None:
    """错误日志：✖ ERROR"""
    print(f"{colorize(ICONS['error'], T.RED)} {colorize('ERROR', T.RED + T.BOLD)} {msg}")


def log_done(msg: str) -> None:
    """完成日志：✓ DONE"""
    print(f"{colorize(ICONS['done'], T.GREEN)} {colorize('DONE', T.GREEN + T.BOLD)}  {msg}")


def log_key(msg: str) -> None:
    """关键日志：✦ KEY"""
    print(f"{colorize(ICONS['key'], T.ORANGE)} {colorize('KEY', T.ORANGE + T.BOLD)}   {msg}")


def stage_bar(stages: list[str], current: str, completed: list[str] | None = None) -> None:
    """打印阶段进度条

    Args:
        stages: 所有阶段名
        current: 当前阶段名
        completed: 已完成的阶段名列表
    """
    completed = set(completed or [])
    parts = []
    for s in stages:
        if s == current:
            parts.append(colorize(f"[{s}]", T.ORANGE + T.BOLD))
        elif s in completed:
            parts.append(colorize(f" {s} ", T.GREEN))
        else:
            parts.append(colorize(f" {s} ", T.GRAY))
    # 使用 · 分隔符代替 ──，避免Web日志中出现无意义分隔线
    print(" · ".join(parts))
    print()


def verdict_panel(verdict: str, n_pass: int = 0, n_warn: int = 0, n_fail: int = 0) -> None:
    """打印审计裁决面板

    verdict: PASS / WARN / FAIL / INCONCLUSIVE / BLOCKED
    """
    v = verdict.upper()
    if v in ("PASS", "PASS_WITH_NOTES"):
        icon = "✓"
        color = T.GREEN
        label = "PASS"
    elif v in ("WARN", "INCONCLUSIVE"):
        icon = "▲"
        color = T.YELLOW
        label = "WARN"
    elif v in ("FAIL", "BLOCKED"):
        icon = "✖"
        color = T.RED
        label = "FAIL"
    else:
        icon = "?"
        color = T.GRAY
        label = v

    line = f"{icon} AUDIT VERDICT: {label}  |  PASS={n_pass}  WARN={n_warn}  FAIL={n_fail}"
    print(colorize(line, color + T.BOLD))
    print()


def highlight_value(value, threshold=None, mode="max", good_if=None) -> str:
    """根据阈值高亮数值

    Args:
        value: 数值或字符串
        threshold: 阈值
        mode: "max" 表示 value>=threshold 时告警, "min" 表示 value<=threshold 时告警
        good_if: 可选 lambda，直接判定是否"好"
    """
    s = str(value)
    try:
        f = float(value)
    except (TypeError, ValueError):
        return s

    if good_if is not None:
        color = T.GREEN if good_if(f) else T.YELLOW
    elif threshold is not None:
        if mode == "max":
            color = T.GREEN if f < threshold else T.YELLOW if f < threshold * 1.2 else T.RED
        else:
            color = T.GREEN if f > threshold else T.YELLOW if f > threshold * 0.8 else T.RED
    else:
        color = T.CYAN
    return colorize(s, color + T.BOLD)


def metric_line(label: str, value, unit: str = "", threshold=None, mode="max", good_if=None) -> None:
    """打印一行指标"""
    hl = highlight_value(value, threshold=threshold, mode=mode, good_if=good_if)
    print(f"  {label:<22} {hl} {unit}")


if __name__ == "__main__":
    # 自检示例
    print_header("终端主题模块自检", dept="THEORY", subtitle="Defense-Team Terminal Theme v1.0")
    log_stage("初始化作战系统")
    log_info("检测到终端颜色支持" if supports_color() else "终端颜色支持已关闭")
    log_warn("这是示例警告")
    stage_bar(["EMBED", "SIMPLEX", "SMAP", "CCM", "HAVOK", "KOOPMAN"], current="CCM", completed=["EMBED", "SIMPLEX", "SMAP"])
    metric_line("max|eig_d|", 1.0007, threshold=1.0, mode="max")
    metric_line("Lyapunov λ", 0.0787, threshold=0.0, mode="max")
    metric_line("CCM coverage", 0.82, threshold=0.5, mode="min")
    verdict_panel("WARN", n_pass=4, n_warn=3, n_fail=0)
    log_done("自检完成")
