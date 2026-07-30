import sys, os, tempfile, subprocess
from pathlib import Path

# 使用相对路径，保证脚本可移植
web_dir = Path(__file__).resolve().parent
skill_dir = web_dir.parent / 'trace-engine' / 'examples' / 'counterfactual_hybrid'
out_dir = Path(tempfile.mkdtemp())
text = '算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。然而，这种个性化推送机制会在长期运行中导致信息茧房效应的形成。信息茧房使得用户长期只接触单一观点，从而加剧了观点极化的趋势。观点极化进一步侵蚀了社会共识的基础。当社会共识瓦解后，公共讨论空间也随之萎缩。公共讨论空间的萎缩又会削弱社会监督功能，社会监督功能的弱化反过来降低算法平台的问责压力。算法平台问责压力的降低，使得算法透明度改革难以推进。算法透明度改革的迟滞进一步固化信息茧房，从而形成一条完整的因果反馈回路。'
proc = subprocess.run(
    [sys.executable, str(web_dir / 'py_bridge.py'), str(skill_dir), str(out_dir), 'deep', '{}'],
    input=text, capture_output=True, text=True, timeout=600,
    env={**os.environ, 'TQDM_DISABLE': '1'},
)
print('RETURN CODE', proc.returncode)
print('--- STDOUT (last 120 lines) ---')
for line in proc.stdout.splitlines()[-120:]:
    print(line)
print('--- STDERR (last 60 lines) ---')
for line in proc.stderr.splitlines()[-60:]:
    print(line)
print('OUT DIR:', out_dir)
if (out_dir / 'result.json').exists():
    print('result.json size:', (out_dir / 'result.json').stat().st_size)
