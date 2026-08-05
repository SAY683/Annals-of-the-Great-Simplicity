#!/usr/bin/env python3
"""
trace-engine Skill 本地 smoke test
==================================

注意：本文件保留为 subprocess + assert 模式的 smoke test，可独立运行：
    python tests/test_skill.py

更细粒度的 pytest 单元测试见同目录其他 test_*.py 文件：
    - test_counterfactual_bridge.py  TRACE2DoWhy 桥接核心功能
    - test_presets.py                预设系统 (presets.yaml / load_presets)
    - test_six_warriors.py           六勇士 (WarriorCard / assemble_all_six)

使用 pytest 框架运行全部测试：
    pytest                            # 通过 pytest.ini 收集 tests/ 下全部 test_*.py

用法:
    python tests/test_skill.py

测试覆盖:
1. 环境检查（关键依赖、模型目录存在性）
2. run_cli.py demo 完整流程
3. run_cli.py env 环境报告
4. 六战士模块可导入
"""

import json
import subprocess
import sys
import traceback
from pathlib import Path

# R50 fix: Windows GBK 控制台无法编码 U+FFFD 替换字符（run() 以 errors='replace'
# 解码子进程输出时产生），导致 print 崩溃 → verify_portable.py 契约 5 FAIL。
# 保留控制台原编码，仅将不可编码字符替换为 '?' 而非抛异常。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(errors='replace')

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / 'examples' / 'counterfactual_hybrid'


def run(cmd, cwd=None, timeout=120):
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    return result


def check_env():
    print("[1/4] 环境检查")
    result = run([sys.executable, 'run_cli.py', 'env'], cwd=EXAMPLES, timeout=60)
    print(result.stdout[-1500:] if len(result.stdout) > 1500 else result.stdout)
    if result.returncode != 0:
        raise AssertionError(f"env 检查失败:\n{result.stderr}")
    if 'MB' not in result.stdout and '模型' not in result.stdout:
        print("  警告: 未检测到模型就绪，部分功能可能不可用")
    print("  [OK] 环境检查通过")


def check_imports():
    print("[2/4] 模块导入检查")
    script = """
import sys
sys.path.insert(0, r'{examples}')
from counterfactual_bridge import TRACE2DoWhy
from six_warriors import assemble_all_six
from project_paths import ProjectPaths
print('counterfactual_bridge, six_warriors, project_paths 导入成功')
""".format(examples=str(EXAMPLES))
    result = run([sys.executable, '-c', script], cwd=ROOT, timeout=60)
    print(result.stdout.strip())
    if result.returncode != 0:
        raise AssertionError(f"模块导入失败:\n{result.stderr}")
    print("  [OK] 模块导入通过")


def check_demo():
    print("[3/4] Demo 流程检查")
    result = run([sys.executable, 'run_cli.py', 'demo'], cwd=EXAMPLES, timeout=120)
    output = result.stdout
    if 'Verdict: PASS' not in output and '完成' not in output:
        print(output[-2000:])
        raise AssertionError(f"demo 流程未正常完成:\n{result.stderr}")
    # 检查输出文件
    report = EXAMPLES / 'outputs' / 'demo' / 'report.md'
    if not report.exists():
        raise AssertionError("demo 未生成 report.md")
    print("  [OK] Demo 流程通过")


def check_six_warriors_robustness():
    print("[4/4] 六战士 concept-level 矩阵鲁棒性检查")
    script = """
import sys
import numpy as np
sys.path.insert(0, r'{examples}')
from six_warriors import assemble_all_six

# 模拟 Web 场景：概念级矩阵 + 原始 token 序列
adj = np.random.rand(12, 12)
adj = (adj + adj.T) / 2
np.fill_diagonal(adj, 0)
tokens = ['概念_' + str(i % 12) for i in range(100)]
concept_names = ['概念_' + str(i) for i in range(12)]

cards = assemble_all_six(adj, tokens, concept_names=concept_names, text='test')
assert 'trace' in cards
assert 'ccm' in cards
assert 'havok' in cards
status_map = dict((k, v.status) for k, v in cards.items())
print('六战士诊断完成:', status_map)
""".format(examples=str(EXAMPLES))
    result = run([sys.executable, '-c', script], cwd=ROOT, timeout=60)
    print(result.stdout.strip())
    if result.returncode != 0:
        raise AssertionError(f"六战士鲁棒性测试失败:\n{result.stderr}")
    print("  [OK] 六战士鲁棒性通过")


def main():
    try:
        check_env()
        check_imports()
        check_demo()
        check_six_warriors_robustness()
        print("\n全部 Skill 测试通过")
    except Exception as e:
        print(f"\n测试失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
