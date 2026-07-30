import sys, os, json, time
sys.path.insert(0, r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web')
os.environ['TRACE_ENGINE_SKILL_DIR'] = r'F:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid'

from llama_worker import run_super_job

text = '算法推荐系统通过持续分析用户行为数据，精准推送用户感兴趣的内容。然而，这种个性化推送机制会在长期运行中导致信息茧房效应的形成。信息茧房使得用户长期只接触单一观点，从而加剧了观点极化的趋势。观点极化进一步侵蚀了社会共识的基础。当社会共识瓦解后，公共讨论空间也随之萎缩。'
job = {'id': 'test-job-1', 'text': text, 'model': 'shehui-llama', 'config': {}, 'timeout_ms': 600000}
t0 = time.time()
run_super_job(job)
print(f'\nFull SUPER elapsed: {time.time()-t0:.1f}s')
