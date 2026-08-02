"""
副本同步检查脚本（NEW-7）。
对比 edm-takens 核心库（src/）与 edm-takens-web 副本（backend/edmtakens/）
中共享文件的 SHA256 校验和，发现不一致时报告差异并以非零退出码退出。

S1-5 修复 (科研披露落地 Round 28): 扩展校验范围至文档层 (docs/ALGORITHM_AUDIT.md),
并新增披露字段存在性检查 (DISCLOSURE_FIELDS), 确保 4 个科研披露字段
(is_strict_confirmatory / methodology_disclaimer / effective_lib_sizes /
out_of_sample_used) 在 ccm_causality.py 和 _numpy_edm.py 中存在定义,
防止未来重构丢失这些科研级披露字段.

用法:
    python sync_check.py          # 检查所有共享文件 + 文档 + 披露字段
    python sync_check.py --quiet  # 仅输出差异，无差异时静默
    python sync_check.py --no-docs  # 跳过文档同步检查
    python sync_check.py --no-disclosure  # 跳过披露字段存在性检查

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
# S1-5 修复: 文档层路径
_CORE_DOCS = os.path.abspath(
    os.path.join(_BACKEND_DIR, "..", "..", "edm-takens", "docs")
)
_WEB_DOCS = os.path.join(_BACKEND_DIR, "..", "docs")

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

# S1-5 修复: 文档层预期差异 (Web 版有 §2.3 节, 核心库也有但内容不同)
# 这两个文档不要求 SHA256 一致, 但要求关键章节存在
EXPECTED_DOC_DIFFERS = {
    "ALGORITHM_AUDIT.md",  # Web 版有额外的 §2.3 节 (科研披露落地记录)
}

# S1-5 修复: 文档层关键章节存在性检查
# 这些章节必须在两份文档中都存在, 否则视为同步失败
# 章节标识符支持多种格式匹配: "§2.3" 或 "### 2.3" 或 "## 2.3"
# 核心库用 "### 2.3" 格式, Web 副本用 "§2.3" 格式, 两者都视为存在
REQUIRED_DOC_SECTIONS = {
    "ALGORITHM_AUDIT.md": [
        "2.3",  # 跨项目同步修复记录 (匹配 "§2.3" / "### 2.3" / "## 2.3")
    ],
}

# S1-5 修复: 披露字段存在性检查
# 这 4 个字段是科研级产品的核心披露, 必须在指定文件中存在定义
# 防止未来重构意外丢失这些字段
DISCLOSURE_FIELDS = {
    "ccm_causality.py": [
        "is_strict_confirmatory",        # BH uniform-null 假设披露
        "methodology_disclaimer",        # 方法学免责声明
    ],
    "_numpy_edm.py": [
        "effective_lib_sizes",           # out-of-sample 实际建树库大小
        "out_of_sample_used",            # 评估模式标志
    ],
}


def _sha256(filepath: str) -> str:
    """计算文件的 SHA256 哈希值。"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_disclosure_fields(quiet: bool) -> int:
    """S1-5 修复: 检查科研披露字段在源文件中存在定义.

    这些字段是科研级产品的核心披露, 防止未来重构意外丢失.
    检查方式: 在文件内容中搜索字段名字符串 (作为 dict key 或属性).
    """
    if not quiet:
        print("\n── 披露字段存在性检查 (S1-5) ──────────────")
    missing = []
    for fname, fields in DISCLOSURE_FIELDS.items():
        # 检查核心库和副本两份
        for src_dir, label in [(_CORE_SRC, "核心库"), (_WEB_EDMTAKENS, "Web 副本")]:
            filepath = os.path.join(src_dir, fname)
            if not os.path.exists(filepath):
                missing.append(f"{label}/{fname} (文件缺失)")
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            for field in fields:
                # 搜索字段名作为 dict key ("field_name") 或赋值 (field_name =)
                # 这是宽松检查, 避免误报; 严格检查需要 AST 解析
                if f'"{field}"' not in content and f"'{field}'" not in content:
                    missing.append(f"{label}/{fname}: 字段 '{field}' 未找到")
                elif not quiet:
                    print(f"  [OK]   {label}/{fname}: '{field}'")

    if missing:
        print(f"\n[FAIL] 披露字段存在性检查失败 ({len(missing)} 项):")
        for m in missing:
            print(f"  - {m}")
        return 1
    elif not quiet:
        print(f"  披露字段检查通过 ({sum(len(v) for v in DISCLOSURE_FIELDS.values()) * 2} 项)")
    return 0


def _check_docs_sync(quiet: bool) -> int:
    """S1-5 修复: 检查文档层同步状态.

    文档不要求 SHA256 一致 (Web 版有额外章节), 但要求关键章节存在.
    章节匹配规则: 搜索 "§X.Y" 或 markdown 标题 "# X.Y" / "## X.Y" / "### X.Y"
    避免匹配到正文中的版本号或行号.
    """
    if not quiet:
        print("\n── 文档同步检查 (S1-5) ──────────────")
    if not os.path.isdir(_CORE_DOCS):
        if not quiet:
            print(f"  [WARN] 核心库文档目录不存在: {_CORE_DOCS}")
        return 0
    if not os.path.isdir(_WEB_DOCS):
        if not quiet:
            print(f"  [WARN] Web 副本文档目录不存在: {_WEB_DOCS}")
        return 0

    import re
    issues = []
    for fname, sections in REQUIRED_DOC_SECTIONS.items():
        core_path = os.path.join(_CORE_DOCS, fname)
        web_path = os.path.join(_WEB_DOCS, fname)
        if not os.path.exists(core_path):
            issues.append(f"核心库文档缺失: {fname}")
            continue
        if not os.path.exists(web_path):
            issues.append(f"Web 副本文档缺失: {fname}")
            continue
        with open(core_path, "r", encoding="utf-8") as f:
            core_content = f.read()
        with open(web_path, "r", encoding="utf-8") as f:
            web_content = f.read()
        for section in sections:
            # 构建章节标题正则: 匹配 "§X.Y" 或 markdown 标题 "X.Y" (前面有 #)
            # 避免匹配到正文中的版本号或行号
            section_pattern = re.compile(
                rf'(?:§{re.escape(section)}|^\s*#+\s*{re.escape(section)}\s)',
                re.MULTILINE
            )
            if not section_pattern.search(core_content):
                issues.append(f"核心库 {fname}: 缺少章节 '{section}'")
            elif not quiet:
                print(f"  [OK]   核心库 {fname}: 章节 '{section}' 存在")
            if not section_pattern.search(web_content):
                issues.append(f"Web 副本 {fname}: 缺少章节 '{section}'")
            elif not quiet:
                print(f"  [OK]   Web 副本 {fname}: 章节 '{section}' 存在")

    if issues:
        print(f"\n[FAIL] 文档同步检查失败 ({len(issues)} 项):")
        for i in issues:
            print(f"  - {i}")
        return 1
    return 0


def main() -> int:
    quiet = "--quiet" in sys.argv
    skip_docs = "--no-docs" in sys.argv
    skip_disclosure = "--no-disclosure" in sys.argv

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

    print("── 源码同步检查 ──────────────")
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
    print(f"\n源码汇总: {matches} 一致 / {expected_differs} 预期差异 / "
          f"{len(mismatches)} 不一致 / {len(only_core)} 副本缺失")

    exit_code = 0
    if mismatches:
        print("\n不一致文件列表:")
        for f in mismatches:
            print(f"  - {f}")
        print("\n请手动同步核心库的更改到副本，或反向同步。")
        exit_code = 1

    # S1-5 修复: 披露字段存在性检查
    if not skip_disclosure:
        if _check_disclosure_fields(quiet) != 0:
            exit_code = 1

    # S1-5 修复: 文档层同步检查
    if not skip_docs:
        if _check_docs_sync(quiet) != 0:
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
