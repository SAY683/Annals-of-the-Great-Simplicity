"""
TRACE 速度预设体系 v3 — 全参数工程优化

设计原则:
  1. 每个预设 = 训练参数 + TRACE 参数 + 架构选择的完整组合
  2. 精度递增: explore → light → standard → heavy → full
  3. 时间递增: ~3min → ~12min → ~25min → ~40min → ~60min
  4. 每个参数都有"为什么这个值"的工程理由

参数影响矩阵:
  训练端: epochs↓ → 速度↑, loss↑ → 质量↓  (强相关)
          vocab↓ → 速度↑↑, 粒度↓ → 质量↓  (最关键!)
          架构↓ → 速度↑↑, expressivity↓    (第二关键)
  TRACE端: window↓ → 速度↑, 长距因果↓     (中等)
           batch↓ → 速度↓, VRAM↓ (安全)    (硬件约束)
           Ghost → 速度↓, 信噪比↑           (必须开)
"""
import math

class TRACEPreset:
    """统一预设 — 包含训练、TRACE、架构全部参数"""

    # 预设定义
    PRESETS = {
        "explore": {
            # ── 训练参数 ──
            "max_epochs": 8, "min_epochs": 2, "patrol": 2,
            "batch": 24, "stride": 128,
            "lr": 3e-4, "warmup": 30,
            # ── 多维早停 ──
            "loss_delta": 0.05, "dnl_stable": 0.30,
            "grad_flat": 0.01, "freq_loss_gap": 0.5,
            "required_signals": 1, "min_loss": 0.8,
            # ── 架构 ──
            "vocab": 2000, "layers": 6, "dim": 256, "heads": 8,
            # ── TRACE 参数 ──
            "trace_window": 32, "trace_batch": 16,
            "ghost": False, "smart_prune": True,
            "threshold_base": 0.5,
            # ── 元信息 ──
            "label": "探索",
            "target_minutes": "3-5",
            "description": "快速判断文本是否有因果结构。精简模型+大batch+粗收敛。",
        },
        "light": {
            "max_epochs": 15, "min_epochs": 4, "patrol": 3,
            "batch": 16, "stride": 64,
            "lr": 3e-4, "warmup": 50,
            "loss_delta": 0.02, "dnl_stable": 0.20,
            "grad_flat": 0.005, "freq_loss_gap": 0.3,
            "required_signals": 2, "min_loss": 0.5,
            "vocab": 3000, "layers": 8, "dim": 320, "heads": 8,
            "trace_window": 64, "trace_batch": 16,
            "ghost": True, "smart_prune": True,
            "threshold_base": 0.5,
            "label": "轻量",
            "target_minutes": "10-15",
            "description": "默认首选。标准架构+Ghost+智能剪枝。大多数场景的最优性价比。",
        },
        "standard": {
            "max_epochs": 25, "min_epochs": 5, "patrol": 5,
            "batch": 14, "stride": 32,
            "lr": 2e-4, "warmup": 80,
            "loss_delta": 0.01, "dnl_stable": 0.12,
            "grad_flat": 0.003, "freq_loss_gap": 0.2,
            "required_signals": 3, "min_loss": 0.2,
            "vocab": 4000, "layers": 8, "dim": 384, "heads": 8,
            "trace_window": 96, "trace_batch": 12,
            "ghost": True, "smart_prune": True,
            "threshold_base": 0.5,
            "label": "标量",
            "target_minutes": "20-30",
            "description": "正式分析。更大词表+更宽模型+更长因果窗口。",
        },
        "heavy": {
            "max_epochs": 40, "min_epochs": 6, "patrol": 5,
            "batch": 12, "stride": 24,
            "lr": 2e-4, "warmup": 100,
            "loss_delta": 0.005, "dnl_stable": 0.08,
            "grad_flat": 0.001, "freq_loss_gap": 0.12,
            "required_signals": 4, "min_loss": 0.12,
            "vocab": 5000, "layers": 10, "dim": 384, "heads": 8,
            "trace_window": 128, "trace_batch": 10,
            "ghost": True, "smart_prune": False,  # 不剪枝 — 要全量精度
            "threshold_base": 0.5,
            "label": "极量",
            "target_minutes": "30-40",
            "description": "高精度。更深模型+全量target+大窗口。接近Qwen的品质。",
        },
        "full": {
            "max_epochs": 60, "min_epochs": 8, "patrol": 8,
            "batch": 8, "stride": 16,
            "lr": 1e-4, "warmup": 150,
            "loss_delta": 0.003, "dnl_stable": 0.04,
            "grad_flat": 0.0005, "freq_loss_gap": 0.06,
            "required_signals": 4, "min_loss": 0.06,
            "vocab": 6000, "layers": 12, "dim": 448, "heads": 8,
            "trace_window": 256, "trace_batch": 8,
            "ghost": True, "smart_prune": False,
            "threshold_base": 0.5,
            "label": "全量",
            "target_minutes": "50-70",
            "description": "归档级。最大模型+最大窗口+零剪枝。品质唯一目标。",
        },
    }

    def __init__(self, preset_name: str):
        if preset_name not in self.PRESETS:
            raise ValueError(f"Unknown preset: {preset_name}. Choose from: {list(self.PRESETS.keys())}")
        self.name = preset_name
        p = self.PRESETS[preset_name]
        for k, v in p.items():
            setattr(self, k, v)

        # 派生值
        emb = self.vocab * self.dim
        body_per_layer = 12 * self.dim * self.dim  # 4*dim^2(QKV) + 8*dim^2(SwiGLU)
        total = 2 * emb + body_per_layer * self.layers
        self.model_size_m = round(total / 1e6, 1)
        self.est_vram_gb = round(self.model_size_m * 0.004 + 0.3, 1)
        self.trace_speed_est = int(800 * (8/max(1,self.layers)) * (256/max(1,self.dim)) * (16/max(1,self.trace_batch)))

    def __repr__(self):
        return (f"TRACEPreset({self.name}): {self.label} | "
                f"{self.layers}L/{self.dim}d | vocab={self.vocab} | "
                f"~{self.target_minutes}min | window={self.trace_window} | "
                f"ghost={self.ghost} | prune={self.smart_prune}")

    def summary(self) -> str:
        p = self.PRESETS[self.name]
        lines = [f"=== {self.label} Preset ({self.name}) ==="]
        lines.append(f"Target: {self.target_minutes} minutes")
        lines.append(f"Description: {self.description}")
        lines.append(f"")
        lines.append(f"Model: {self.layers}L/{self.dim}d/{self.heads}h, vocab={self.vocab}")
        lines.append(f"       ~{self.model_size_m:.0f}M params, ~{self.est_vram_gb:.1f}GB VRAM")
        lines.append(f"Estimated TRACE speed: {self.trace_speed_est} pairs/s")
        lines.append(f"")
        lines.append(f"Training: {self.max_epochs} epochs max, batch={self.batch}")
        lines.append(f"          stride={self.stride}, lr={self.lr}, warmup={self.warmup}")
        lines.append(f"          early-stop: {self.required_signals}/{4} signals, patrol={self.patrol}")
        lines.append(f"          safety: min_loss<{self.min_loss}")
        lines.append(f"")
        lines.append(f"TRACE:    window={self.trace_window}, batch={self.trace_batch}")
        lines.append(f"          ghost={self.ghost}, smart_prune={self.smart_prune}")
        lines.append(f"          threshold_base={self.threshold_base}")
        return "\n".join(lines)

    @classmethod
    def recommend(cls, text_len: int, text_type: str = "unknown",
                  time_budget_min: int = None, quality_need: str = "explore") -> str:
        """
        自动推荐预设。

        Args:
            text_len: 文本长度 (字符)
            text_type: "argumentative" | "narrative" | "unknown"
            time_budget_min: 时间预算 (分钟), None = 不限
            quality_need: "explore" | "standard" | "publish"
        """
        # 基础推荐: 根据长度
        if text_len < 1000:
            base = "light"
        elif text_len < 5000:
            base = "standard"
        else:
            base = "heavy"

        # 调整: 论述文 → 可以用更高精度 (CCM 有效)
        if text_type == "argumentative" and quality_need != "explore":
            base = {"light": "standard", "standard": "heavy", "heavy": "full"}.get(base, base)

        # 调整: 时间预算 (用 epochs 比较)
        _order = {"explore": 0, "light": 1, "standard": 2, "heavy": 3, "full": 4}
        if time_budget_min and time_budget_min < 10:
            if quality_need == "publish": return "light"
            return "explore"
        if time_budget_min and time_budget_min < 20:
            if _order[base] > _order["light"]: return "light"
            return base

        return base


# ============================================================
# 演示
# ============================================================
if __name__ == "__main__":
    for name in ["explore", "light", "standard", "heavy", "full"]:
        preset = TRACEPreset(name)
        print(preset.summary())
        print()

    print("=" * 60)
    print("Auto-recommendation tests:")
    print("=" * 60)
    tests = [
        (500, "unknown", None, "explore"),
        (3000, "narrative", 15, "explore"),
        (5000, "argumentative", None, "standard"),
        (8000, "argumentative", 60, "publish"),
    ]
    for text_len, text_type, budget, quality in tests:
        rec = TRACEPreset.recommend(text_len, text_type, budget, quality)
        print(f"  {text_len}chars, {text_type}, {budget}min budget, {quality} → {rec}")
