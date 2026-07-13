import sys, json, traceback
import numpy as np
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter
from enhanced_viz import render_dashboard
from project_paths import resolve_paths

paths = resolve_paths()
adj = np.load(str(paths.outputs_dir / 'cache' / 'real_adj.npy'))
tokens = json.loads((paths.outputs_dir / 'cache' / 'real_tokens.json').read_text(encoding='utf-8'))

bridge = TRACE2DoWhy(adj, tokens, threshold=0.2, concept_min_freq=2, random_state=42)
bridge.aggregate_concepts()
bridge.build_model()
bridge.identify()
bridge.estimate()
bridge.refute()
bridge.counterfactual_scan(n_top_edges=min(5, len(bridge.significant_edges)))

try:
    p = render_dashboard(bridge, str(paths.outputs_dir / 'real' / 'repro_dashboard.png'), dpi=100)
    print('OK:', p)
except Exception as e:
    print('ERROR:', e)
    traceback.print_exc()
