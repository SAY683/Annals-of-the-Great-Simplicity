"""
副本同步检查脚本（NEW-7）。
对比 edm-takens 核心库（src/）与 edm-takens-web 副本（backend/edmtakens/）
中共享文件的 SHA256 校验和，发现不一致时报告差异并以非零退出码退出。

用法:
    python sync_check.py          # 检查所有共享文件
    python sync_check.py --quiet  # 仅输出差异，无差异时静默

注意：_paths.py 在副本中被有意修改（支持 EDMTAKENS_DATA_DIR 环境变量），
故列入 EXPECTED_DIFFERS 白名单，不视为同步失败。
"""
import hashlib
import os
import sys

# ── 路径配置 ──────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_WEB_EDMTAKENS = os.path.join(_BACKEND_DIR, "edmtakens")
_CORE_SRC = os.path.abspath(
    os.path.join(_BACKEND_DIR, "..", "..", "edm-takens", "src")
)

# 副本中独有的文件（核心库不存在），跳过检查
# 修缮 A4 已将 data_quality.py 和 analysis_profiles.py 回迁到核心库 src/，
# 两份副本现在完全一致，不再属于 web 独有文件；移出白名单后由 sync_check
# 持续监控一致性，防止未来再次漂移。
WEB_ONLY_FILES: set = set()

# 有意差异的文件（副本因 web 环境需求做了定制），不视为同步失败
EXPECTED_DIFFERS = {
    "_paths.py",                  # 副本支持 EDMTAKENS_DATA_DIR 环境变量
    "__init__.py",                # 副本为 backend 包说明注释，与核心库源码包注释不同
}


def _sha256(filepath: str) -> str:
    """计算文件的 SHA256 哈希值。"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    quiet = "--quiet" in sys.argv

    if not os.path.isdir(_CORE_SRC):
        print(f"[ERROR] 核心库目录不存在: {_CORE_SRC}", file=sys.stderr)
        return 2
    if not os.path.isdir(_WEB_EDMTAKENS):
        print(f"[ERROR] 副本目录不存在: {_WEB_EDMTAKENS}", file=sys.stderr)
        return 2

    core_files = {
        f for f in os.listdir(_CORE_SRC)
        if f.endswith(".py") and f not in WEB_ONLY_FILES
    }
    web_files = {
        f for f in os.listdir(_WEB_EDMTAKENS)
        if f.endswith(".py") and f not in WEB_ONLY_FILES
    }

    common = sorted(core_files & web_files)
    only_core = sorted(core_files - web_files)
    only_web = sorted(web_files - core_files)

    mismatches = []
    matches = 0
    expected_differs = 0

    for fname in common:
        core_hash = _sha256(os.path.join(_CORE_SRC, fname))
        web_hash = _sha256(os.path.join(_WEB_EDMTAKENS, fname))
        if core_hash == web_hash:
            matches += 1
            if not quiet:
                print(f"  [OK]   {fname}")
        else:
            if fname in EXPECTED_DIFFERS:
                expected_differs += 1
                if not quiet:
                    print(f"  [SKIP] {fname}  (预期差异：副本定制)")
            else:
                mismatches.append(fname)
                print(f"  [DIFF] {fname}  核心库与副本不一致！")

    # 报告仅存在于一方的文件
    for fname in only_core:
        print(f"  [WARN] {fname} 仅存在于核心库，副本缺失")
    for fname in only_web:
        print(f"  [INFO] {fname} 仅存在于副本（web 专有）")

    # 汇总
    print(f"\n汇总: {matches} 一致 / {expected_differs} 预期差异 / "
          f"{len(mismatches)} 不一致 / {len(only_core)} 副本缺失")

    if mismatches:
        print("\n不一致文件列表:")
        for f in mismatches:
            print(f"  - {f}")
        print("\n请手动同步核心库的更改到副本，或反向同步。")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
