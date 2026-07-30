import sys
import py_bridge

skill_dir = r'f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid'
out_dir = r'f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\test_out'
text = open(r'f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\sample_input.txt', encoding='utf-8').read()

sys.argv = ['py_bridge.py', skill_dir, out_dir, 'light', '{}', '']
# 替换stdin
import io
sys.stdin = io.StringIO(text)
py_bridge.main()
