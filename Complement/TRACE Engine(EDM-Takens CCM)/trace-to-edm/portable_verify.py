"""
trace-to-edm 便携式移植验证脚本
================================
验证便携式目录的完整性，包括:
  1. 目录结构完整性
  2. sacred_texts/ 8 本经书存在
  3. config.py 便携式布局探测正确
  4. Python 模块导入正常
  5. server.js 语法正确
  6. 与 trace-engine-web 的路径对接正确

用法:
  python portable_verify.py
"""
import os
import sys
import json
from pathlib import Path

# ── 配置 ────────────────────────────────────────────────────
HERE = Path(os.path.dirname(os.path.abspath(__file__)))

# 期望的经书列表（与 config.SACRED_BOOKS 一致）
EXPECTED_BOOKS = [
    "01_fuyin_祂志书.txt",
    "02_jixiang_赐福书.txt",
    "03_aomei_圣源书.txt",
    "04_cunzai_真实书.txt",
    "05_ziyun_胜育书.txt",
    "06_misaiya_至意书.txt",
    "07_alice_慧辩书.txt",
    "08_jueai_智识书.txt",
]

# 期望的顶层 Python 模块
EXPECTED_PY_MODULES = [
    "config.py",
    "bridge.py",
    "csv_builder.py",
    "dataset_manager.py",
    "edm_trigger.py",
    "layer1_meta_scm.py",
    "layer2_semantic.py",
    "layer3_sacred.py",
    "project_manager.py",
    "work_scanner.py",
    "__init__.py",
]

# 期望的顶层资源文件
EXPECTED_TOP_FILES = [
    "server.js",
    "package.json",
    "requirements.txt",
    "README.md",
    "portable_start.bat",
]


# ── 结果收集 ────────────────────────────────────────────────
class Result:
    def __init__(self):
        self.passed = []
        self.warnings = []
        self.failed = []

    def ok(self, msg):
        self.passed.append(msg)
        print(f"  [PASS] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  [WARN] {msg}")

    def fail(self, msg):
        self.failed.append(msg)
        print(f"  [FAIL] {msg}")

    def is_success(self):
        return len(self.failed) == 0


R = Result()


# ── 验证步骤 ────────────────────────────────────────────────
def verify_directory_structure():
    """1. 目录结构完整性。"""
    print("\n[1/8] 验证目录结构完整性")

    # 顶层 Python 模块
    for name in EXPECTED_PY_MODULES:
        f = HERE / name
        if f.exists() and f.is_file():
            R.ok(f"Python 模块: {name}")
        else:
            R.fail(f"缺失 Python 模块: {name}")

    # 顶层资源文件
    for name in EXPECTED_TOP_FILES:
        f = HERE / name
        if f.exists() and f.is_file():
            R.ok(f"资源文件: {name}")
        else:
            R.fail(f"缺失资源文件: {name}")

    # 顶层目录
    for d in ("public", "sacred_texts", "data", "projects"):
        p = HERE / d
        if p.exists() and p.is_dir():
            R.ok(f"目录: {d}/")
        else:
            R.fail(f"缺失目录: {d}/")

    # data/ 子目录骨架
    for sub in ("inputs", "outputs", "cache"):
        p = HERE / "data" / sub
        if p.exists() and p.is_dir():
            R.ok(f"运行时骨架: data/{sub}/")
        else:
            R.fail(f"缺失运行时骨架: data/{sub}/")

    # public/ 子结构
    for sub in ("css", "js"):
        p = HERE / "public" / sub
        if p.exists() and p.is_dir():
            R.ok(f"public/{sub}/")
        else:
            R.fail(f"缺失 public/{sub}/")

    # public/index.html
    idx = HERE / "public" / "index.html"
    if idx.exists():
        R.ok("public/index.html")
    else:
        R.fail("缺失 public/index.html")


def verify_sacred_texts():
    """2. sacred_texts/ 8 本经书存在。"""
    print("\n[2/8] 验证 sacred_texts/ 8 本经书")
    sacred_dir = HERE / "sacred_texts"
    if not sacred_dir.exists():
        R.fail(f"sacred_texts/ 目录不存在")
        return

    for book in EXPECTED_BOOKS:
        p = sacred_dir / book
        if p.exists() and p.is_file():
            size = p.stat().st_size
            if size > 0:
                R.ok(f"{book} ({size} bytes)")
            else:
                R.fail(f"{book} 为空文件")
        else:
            R.fail(f"缺失经书: {book}")


def verify_config_portable_detection():
    """3. config.py 便携式布局探测正确。"""
    print("\n[3/8] 验证 config.py 便携式布局探测")
    try:
        # 切换 CWD 到 HERE 以模拟便携式运行
        original_cwd = os.getcwd()
        os.chdir(HERE)
        sys.path.insert(0, str(HERE))

        # 强制重新导入 config
        for mod_name in list(sys.modules.keys()):
            if mod_name == "config" or mod_name.startswith("config."):
                del sys.modules[mod_name]

        import config

        # 检查便携式布局标志
        if not getattr(config, "IS_PORTABLE_LAYOUT", False):
            R.fail(f"config.IS_PORTABLE_LAYOUT = False（应为 True）")
        else:
            R.ok("config.IS_PORTABLE_LAYOUT = True")

        # 检查 Qwen 模型路径是否指向便携式 Models/
        qwen_1_5b = config.QWEN_MODEL_PATH
        if "Models" in str(qwen_1_5b) and "Qwen2.5-1.5B-Instruct" in str(qwen_1_5b):
            R.ok(f"QWEN_MODEL_PATH = {qwen_1_5b}")
        else:
            R.fail(f"QWEN_MODEL_PATH 未指向便携式 Models/: {qwen_1_5b}")

        qwen_3b = config.QWEN_MODEL_PATH_3B
        if "Models" in str(qwen_3b) and "Qwen2.5-3B-Instruct" in str(qwen_3b):
            R.ok(f"QWEN_MODEL_PATH_3B = {qwen_3b}")
        else:
            R.fail(f"QWEN_MODEL_PATH_3B 未指向便携式 Models/: {qwen_3b}")

        # 检查 EDM_TAKENS_DIR 指向 edm-takens-web
        # R50 fix: 便携目录已改为同级布局 (TRACE Engine(EDM-Takens CCM)/edm-takens-web),
        # 不再要求路径含 Skill/; 仅要求目录存在且名为 edm-takens-web。
        edm_dir = config.EDM_TAKENS_DIR
        if edm_dir.exists() and edm_dir.name == "edm-takens-web":
            R.ok(f"EDM_TAKENS_DIR = {edm_dir}")
        else:
            R.fail(f"EDM_TAKENS_DIR 未指向 edm-takens-web: {edm_dir}")

        # 检查 Qwen 模型实际存在
        if qwen_1_5b.exists():
            R.ok(f"Qwen 1.5B 模型存在: {qwen_1_5b}")
        else:
            R.fail(f"Qwen 1.5B 模型不存在: {qwen_1_5b}")

        if qwen_3b.exists():
            R.ok(f"Qwen 3B 模型存在: {qwen_3b}")
        else:
            R.warn(f"Qwen 3B 模型不存在（可选）: {qwen_3b}")

        # 检查 trace-engine-web 对接（同级）
        trace_web = config.TRACE_ENGINE_WEB_DIR
        if trace_web.exists():
            R.ok(f"trace-engine-web 对接: {trace_web}")
        else:
            R.fail(f"trace-engine-web 不存在: {trace_web}")

        # 恢复 CWD
        os.chdir(original_cwd)
    except Exception as e:
        R.fail(f"config.py 导入异常: {e}")


def verify_python_imports():
    """4. Python 模块导入正常。"""
    print("\n[4/8] 验证 Python 模块导入")
    original_cwd = os.getcwd()
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))

    # 清理已导入的本地模块
    local_modules = [
        "config", "bridge", "csv_builder", "dataset_manager",
        "edm_trigger", "layer1_meta_scm", "layer2_semantic",
        "layer3_sacred", "project_manager", "work_scanner",
    ]
    for mod_name in list(sys.modules.keys()):
        for local in local_modules:
            if mod_name == local or mod_name.startswith(local + "."):
                del sys.modules[mod_name]
                break

    # 逐个导入核心模块
    for mod_name in local_modules:
        try:
            __import__(mod_name)
            R.ok(f"import {mod_name}")
        except Exception as e:
            R.fail(f"import {mod_name} 失败: {e}")

    os.chdir(original_cwd)


def verify_server_js_syntax():
    """5. server.js 语法正确。"""
    print("\n[5/8] 验证 server.js 语法")
    server_js = HERE / "server.js"
    if not server_js.exists():
        R.fail("server.js 不存在")
        return

    # 用 node --check 验证语法
    try:
        import subprocess
        result = subprocess.run(
            ["node", "--check", str(server_js)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            R.ok("server.js 语法正确")
        else:
            R.fail(f"server.js 语法错误: {result.stderr.strip()}")
    except FileNotFoundError:
        R.warn("node 未安装，跳过 server.js 语法检查")
    except Exception as e:
        R.warn(f"无法验证 server.js 语法: {e}")


def verify_default_project_cleanliness():
    """7. default 项目数据清洁度检查 (CHK-02).

    default 项目是便携式模板项目，不应残留 text-* 测试条目。
    若存在 text-* 条目，说明开发期的测试数据未清理，会污染便携式分发。
    """
    print("\n[8/8] 验证 default 项目数据清洁度")
    default_dir = HERE / "projects" / "default"
    dataset_path = default_dir / "dataset.json"
    if not dataset_path.exists():
        R.ok("projects/default/dataset.json 不存在（首次运行时自动创建）")
        return

    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        R.fail(f"读取 projects/default/dataset.json 失败: {e}")
        return

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        R.fail(f"projects/default/dataset.json entries 字段非数组")
        return

    # CHK-02: default 项目不应包含 text-* 测试条目
    text_entries = [
        e for e in entries
        if isinstance(e, dict) and isinstance(e.get("id", ""), str)
        and e["id"].startswith("text-")
    ]
    if not text_entries:
        R.ok(f"default 项目无 text-* 测试条目 (共 {len(entries)} 条 replay 条目)")
    else:
        sample_ids = ", ".join(e["id"] for e in text_entries[:5])
        R.fail(
            f"default 项目包含 {len(text_entries)} 条 text-* 测试条目（便携式分发前应清理）。"
            f" 示例 id: {sample_ids}"
        )


def verify_trace_engine_web_bridge():
    """6. 与 trace-engine-web 的路径对接正确。"""
    print("\n[6/8] 验证与 trace-engine-web 路径对接")
    trace_web = HERE.parent / "trace-engine-web"
    if not trace_web.exists():
        R.fail(f"trace-engine-web 不存在: {trace_web}")
        return

    R.ok(f"trace-engine-web 存在: {trace_web}")

    # 检查 py_bridge.py
    py_bridge = trace_web / "py_bridge.py"
    if py_bridge.exists():
        R.ok(f"py_bridge.py 存在")
    else:
        R.fail(f"py_bridge.py 不存在: {py_bridge}")

    # 检查 work/outputs/
    work_outputs = trace_web / "work" / "outputs"
    if work_outputs.exists():
        R.ok(f"work/outputs/ 存在")
    else:
        R.warn(f"work/outputs/ 不存在（首次运行时自动创建）: {work_outputs}")

    # 检查 EDM-Takens Web（当前便携布局为同级，旧布局在 Skill/ 下）
    # R50 fix: 便携目录已改为同级布局, edm-takens-web 与 trace-to-edm 同级。
    edm_web = HERE.parent / "edm-takens-web"
    if not edm_web.exists():
        edm_web = HERE.parent.parent / "Skill" / "edm-takens-web"
    if edm_web.exists():
        R.ok(f"edm-takens-web 存在: {edm_web}")
    else:
        R.warn(f"edm-takens-web 不存在（可选）: {edm_web}")


def verify_methodology_audit():
    """7. 方法学审计契约 (ROUND28 P0-02/P0-04/P2-03).

    验证三项:
      a. ALGORITHM_AUDIT.md 存在 (layer3_sacred.py 引用 "详见 ALGORITHM_AUDIT.md §3");
      b. layer3_sacred.METHODOLOGY_TAG / METHODOLOGY_DISCLAIMER 可导入且非空;
      c. csv_builder.COLUMN_COUNT == 88 (列总数契约, 防止 LAYER1_COLUMNS/SACRED_BOOKS
         变更后列数漂移不被发现).
    """
    print("\n[7/8] 验证方法学审计契约")

    # a. ALGORITHM_AUDIT.md 存在性
    audit_md = HERE / "ALGORITHM_AUDIT.md"
    if audit_md.exists() and audit_md.is_file():
        size = audit_md.stat().st_size
        if size > 500:
            R.ok(f"ALGORITHM_AUDIT.md 存在 ({size} bytes)")
        else:
            R.fail(f"ALGORITHM_AUDIT.md 过小 ({size} bytes), 疑似占位文件")
    else:
        R.fail("缺失 ALGORITHM_AUDIT.md (layer3_sacred.py 引用此文件 §3)")

    # b. layer3_sacred 方法学常量
    original_cwd = os.getcwd()
    os.chdir(HERE)
    sys.path.insert(0, str(HERE))
    # 清理已导入的本地模块以避免缓存
    for mod_name in list(sys.modules.keys()):
        if mod_name == "layer3_sacred" or mod_name == "csv_builder" or mod_name == "config":
            del sys.modules[mod_name]
    try:
        import layer3_sacred
        tag = getattr(layer3_sacred, "METHODOLOGY_TAG", None)
        disclaimer = getattr(layer3_sacred, "METHODOLOGY_DISCLAIMER", None)
        if tag == "interpretive_zero_shot":
            R.ok(f"layer3_sacred.METHODOLOGY_TAG = {tag!r}")
        else:
            R.fail(f"layer3_sacred.METHODOLOGY_TAG 非预期: {tag!r} (期望 'interpretive_zero_shot')")
        if disclaimer and len(disclaimer) > 20 and "诠释" in disclaimer:
            R.ok(f"layer3_sacred.METHODOLOGY_DISCLAIMER 存在 ({len(disclaimer)} 字符)")
        else:
            R.fail(f"layer3_sacred.METHODOLOGY_DISCLAIMER 缺失或不含'诠释': {disclaimer!r}")

        # c. csv_builder 列总数契约
        import csv_builder
        col_count = getattr(csv_builder, "COLUMN_COUNT", None)
        if col_count == 88:
            R.ok(f"csv_builder.COLUMN_COUNT = {col_count} (契约一致)")
        else:
            R.fail(f"csv_builder.COLUMN_COUNT = {col_count} (期望 88, 列数契约漂移)")
    except Exception as e:
        R.fail(f"方法学常量导入异常: {e}")
    finally:
        os.chdir(original_cwd)


# ── 主入口 ─────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("trace-to-edm 便携式移植验证")
    print(f"目录: {HERE}")
    print("=" * 60)

    verify_directory_structure()
    verify_sacred_texts()
    verify_config_portable_detection()
    verify_python_imports()
    verify_server_js_syntax()
    verify_trace_engine_web_bridge()
    verify_methodology_audit()
    verify_default_project_cleanliness()

    print("\n" + "=" * 60)
    print(f"通过: {len(R.passed)}  警告: {len(R.warnings)}  失败: {len(R.failed)}")
    print("=" * 60)

    if R.is_success():
        print("\n[SUCCESS] 便携式移植验证通过")
        if R.warnings:
            print(f"  （有 {len(R.warnings)} 个警告，请检视上方输出）")
        return 0
    else:
        print("\n[FAILED] 便携式移植验证未通过")
        for msg in R.failed:
            print(f"  - {msg}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
