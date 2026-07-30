import sys, os, time
sys.path.insert(0, r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web')
# 设置模型目录环境变量，让 project_paths 能找到模型
os.environ['TRACE_ENGINE_SKILL_DIR'] = r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid'

import tempfile
from llama_worker import MODEL_CACHE, compute_trace

text = '算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。然而，这种个性化推送机制会在长期运行中导致信息茧房效应的形成。信息茧房使得用户长期只接触单一观点，从而加剧了观点极化的趋势。'
print('Loading model...')
t0 = time.time()
model, sp = MODEL_CACHE.load('shehui-llama')
print(f'Model loaded in {time.time()-t0:.1f}s')
print('Running compute_trace...')
t0 = time.time()
adj, tokens = compute_trace(text, model, sp, window=64, max_segments=4, job_id=None)
elapsed = time.time() - t0
pairs = int((adj > 0).sum())
print(f'Done: {len(tokens)} tokens, {pairs} edges, {elapsed:.2f}s, ~{pairs/max(elapsed,0.001):.1f} pairs/s')
print('Max delta_nll:', adj.max())
