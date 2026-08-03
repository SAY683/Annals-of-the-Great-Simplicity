"""
将 trace-engine 与 trace-engine-web 同步到成品目录，并重新整理为子目录结构。
排除运行时产物（outputs, __pycache__, .git, node_modules, work 等）。

路径可通过环境变量覆盖，默认基于脚本自身位置自动推断（无硬编码绝对路径）：
  TRACE_PRODUCT_DIR  -> 成品目录（必填，未设置时仅打印提示并退出）
  TRACE_SRC_ENGINE   -> trace-engine 源码目录（默认从脚本位置推断）
  TRACE_SRC_WEB      -> trace-engine-web 源码目录（默认从脚本位置推断）
  TRACE_SRC_DATA     -> 测试数据目录（默认从脚本位置推断）
"""
import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

# P0-03 修复：移除所有硬编码绝对路径，改为基于脚本自身位置推断。
# 支持两种布局：
#   1. 开发布局：脚本在 trace-engine-web/work/sync_product.py
#      → trace-engine-web = script.parent.parent, trace-engine = script.parent.parent.parent / 'trace-engine'
#   2. 自包含/便携布局：脚本在成品根 sync_product.py（同级有 trace-engine/ 和 trace-engine-web/）
#      → 成品根 = script.parent，此时同步操作为自我覆盖，仅用于清理运行时产物
_SCRIPT_PATH = Path(__file__).resolve()
_SCRIPT_DIR = _SCRIPT_PATH.parent

# 检测是否为自包含布局（脚本所在目录直接包含 trace-engine/ 和 trace-engine-web/）
_SELF_CONTAINED = (_SCRIPT_DIR / 'trace-engine').is_dir() and (_SCRIPT_DIR / 'trace-engine-web').is_dir()

if _SELF_CONTAINED:
    # 自包含布局：脚本在成品根
    _WEB_ROOT = _SCRIPT_DIR / 'trace-engine-web'
    _SKILLS_ROOT = _SCRIPT_DIR
else:
    # 开发布局：脚本在 trace-engine-web/work/sync_product.py
    _WEB_ROOT = _SCRIPT_PATH.parent.parent  # trace-engine-web/
    _SKILLS_ROOT = _WEB_ROOT.parent          # .skills/ 或成品根

# 成品目录：必须通过环境变量或命令行参数指定，不再硬编码 fallback
_env_product = os.environ.get('TRACE_PRODUCT_DIR')
if _env_product:
    product = Path(_env_product)
else:
    # 自动探测：若当前处于便携布局（.skills 同级有 TRACE Engine(EDM-Takens CCM)），则使用之
    _candidate_portable = _SKILLS_ROOT / 'TRACE Engine(EDM-Takens CCM)'
    if _candidate_portable.exists():
        product = _candidate_portable
    elif _SELF_CONTAINED:
        # 自包含布局：成品目录就是脚本所在目录
        product = _SCRIPT_DIR
        print(f'[sync_product] 检测到自包含布局，成品目录 = 脚本所在目录: {product}')
        print('[sync_product] 警告：自包含布局下同步操作为自我覆盖，仅用于清理运行时产物和验证完整性。')
        print('[sync_product] 若需从开发布局同步到独立便携目录，请设置 TRACE_PRODUCT_DIR 环境变量。')
    else:
        print('[sync_product] 错误：TRACE_PRODUCT_DIR 环境变量未设置，且未探测到便携布局。')
        print('[sync_product] 请通过环境变量 TRACE_PRODUCT_DIR 或命令行参数 --product 指定成品目录。')
        sys.exit(2)

# 源码目录：基于脚本位置推断，可被环境变量覆盖
src_engine = Path(os.environ.get('TRACE_SRC_ENGINE') or (_SKILLS_ROOT / 'trace-engine'))
src_web = Path(os.environ.get('TRACE_SRC_WEB') or _WEB_ROOT)
src_data = Path(os.environ.get('TRACE_SRC_DATA') or (_SKILLS_ROOT / 'trace-engine' / 'date'))

# ROUND28 新增: EDM-TAKENS 核心库与 Web 项目源码路径
# 在自包含便携布局下, _SKILLS_ROOT 指向便携目录本身,
# 但 EDM-TAKENS 开发源码位于便携目录的父级 Skill/ 目录.
# 因此需要探测多个候选路径, 找到真正的开发源码.
_dev_skill_root = _SKILLS_ROOT  # 开发布局: .skills/ 或 Skill/
if _SELF_CONTAINED:
    # 自包含布局: 便携目录的父级可能有 Skill/ 目录
    _candidate_skill = _SCRIPT_DIR.parent / 'Skill'
    if _candidate_skill.is_dir():
        _dev_skill_root = _candidate_skill
    else:
        # 也可能在 .skills/ 目录下
        _candidate_dot_skills = _SCRIPT_DIR.parent / '.skills'
        if _candidate_dot_skills.is_dir():
            _dev_skill_root = _candidate_dot_skills

src_edm_takens = Path(os.environ.get('TRACE_SRC_EDM_TAKENS') or (_dev_skill_root / 'edm-takens'))
src_edm_takens_web = Path(os.environ.get('TRACE_SRC_EDM_TAKENS_WEB') or (_dev_skill_root / 'edm-takens-web'))

dst_engine = product / 'trace-engine'
dst_web = product / 'trace-engine-web'
# ROUND28 新增: 便携目录下的 EDM-TAKENS 目标路径
dst_edm_takens = product / 'edm-takens'
dst_edm_takens_web = product / 'edm-takens-web'

# 运行时产物排除模式
engine_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    'outputs', 'work', 'node_modules', 'package-lock.json'
)
web_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    'node_modules', 'package-lock.json', 'work', 'outputs',
    'uploads', 'web_*_result*.json', 'test_min*.bat', '18)',
    # R37-B 修复 (ROUND37 P0): round33_* 运行时测试产物排除.
    # 病灶: Skill/trace-engine-web 中残留 round33_*_results.json, round33_e2e_test.*,
    # sample_input.txt 等测试产物, 未在 ignore 列表中, 同步会反向污染便携目录.
    'round33_*', 'sample_input.txt',
    # R37-B 修复: tunnel_logs/ 运行时日志目录排除
    'tunnel_logs',
)
# ROUND28 新增: EDM-TAKENS 核心库排除模式
# 排除 __pycache__、.git、生成的图片、运行时输出
edm_takens_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    '*.png', 'outputs', 'work', '.pytest_cache'
)
# ROUND28 新增: EDM-TAKENS Web 排除模式
# 排除 node_modules、__pycache__、运行时输出
# P1 修缮（2026-08-03）: 新增 jobs.sqlite / *.sqlite / *.db 排除,
# 防止 edm-takens-web 运行时生成的任务数据库被反向同步污染源码目录与便携目录。
# 病灶: backend/job_store.py:206 默认将 jobs.sqlite 写入项目根 (edm-takens-web/),
# 原版 ignore 未排除 → 同步时该文件会被复制到便携目录, 携带旧任务历史与可能的敏感数据。
# P0 修缮（ROUND32 三视角评审-架构师）: 新增 results 排除,
# 病灶: results/<job_id>/config_*.json 含开发者用户名绝对路径
# (C:\Users\SAY\AppData\Local\Temp\edmtakens_*.csv), 同步会泄露开发者环境
# 且携带旧任务历史时间戳, 违反 "Runtime artifacts must be excluded from packaging".
edm_takens_web_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    'node_modules', 'package-lock.json', 'work', 'outputs',
    'uploads', '*.log', 'data/uploads', '.pytest_cache',
    # P1 修缮: 运行时 SQLite 数据库防护
    'jobs.sqlite', '*.sqlite', '*.sqlite-journal', '*.sqlite-wal', '*.sqlite-shm', '*.db',
    # P0 修缮: 运行时分析结果目录 (含绝对路径泄露)
    'results',
    # R36-A 修复 (ROUND36 P1 安全): .env 文件排除, 防止 API 密钥等敏感信息泄露
    '.env', '.env.local', '.env.*',
    # R37-B 修复 (ROUND37 P0): round33_* 运行时测试产物排除.
    # 病灶: Skill/edm-takens-web 中残留 round33_e_direct_*.json, round33_e_direct_analysis.py,
    # round33_e_three_perspectives.json 等测试产物, 未在 ignore 列表中,
    # sync_edm_takens_projects() 会将其复制到便携目录, 反向污染.
    'round33_e_*', 'round33_*_results.json', 'round33_*_result.json',
    'round33_e2e_test.*', 'sample_input.txt',
)


def safe_rmtree(path: Path):
    if path.exists():
        shutil.rmtree(path)


def _clean_directory_contents(dst: Path, keep: set):
    """清空 dst 下除 keep 外的所有内容，用于目录被锁定时避免 rmtree(dst)。"""
    removed = 0
    for item in dst.iterdir():
        if item.name in keep:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
            removed += 1
        except Exception as e:
            print(f'  无法清理 {item.name}: {e}')
    return removed


def safe_copytree(src: Path, dst: Path, ignore, preserve=None):
    """复制目录，删除 dst 前先保留指定子目录（如 node_modules）。

    若 dst 被其它进程占用导致无法删除，则改为清空 dst 内部内容（保留 preserve 项），
    再 dirs_exist_ok=True 覆盖，避免旧文件残留。
    """
    preserve = preserve or []
    preserved = []
    dst_existed = dst.exists()
    if preserve and dst_existed:
        for name in preserve:
            src_item = dst / name
            if src_item.exists():
                tmp = Path(tempfile.gettempdir()) / f'trace_sync_preserve_{name}_{os.getpid()}'
                if tmp.exists():
                    safe_rmtree(tmp)
                try:
                    shutil.move(str(src_item), str(tmp))
                    preserved.append((name, tmp))
                except Exception as e:
                    print(f'  无法保留 {name}: {e}')
    if dst_existed:
        try:
            safe_rmtree(dst)
            shutil.copytree(src, dst, ignore=ignore)
        except PermissionError as e:
            print(f'  警告: 无法删除旧目录 {dst}（可能被占用: {e}），改为清空内部内容后覆盖...')
            keep = set(preserve) | {name for name, _ in preserved}
            cleaned = _clean_directory_contents(dst, keep)
            shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
            print(f'  覆盖完成（清理 {cleaned} 项旧内容）')
    else:
        shutil.copytree(src, dst, ignore=ignore)
    for name, tmp in preserved:
        target = dst / name
        if tmp.exists():
            try:
                if target.exists():
                    safe_rmtree(target)
                shutil.move(str(tmp), str(target))
                print(f'  保留: {name}')
            except Exception as e:
                print(f'  无法恢复保留项 {name}: {e}')


def copy_existing_root_to_engine():
    """将成品目录根下现有内容迁移到 trace-engine/ 子目录。

    保留 verify_portable.py、sync_product.py 与 README.md 在成品根，便于用户直接运行审计、重新同步和查阅说明。
    """
    dst_engine.mkdir(parents=True, exist_ok=True)
    keep_root = {'verify_portable.py', 'sync_product.py', 'README.md'}
    # trace-to-edm 与 Models 应保留在成品根目录，与 trace-engine、trace-engine-web 同级
    # ROUND28: 新增 edm-takens 和 edm-takens-web 作为同级保留项
    keep_siblings = {'trace-engine', 'trace-engine-web', 'trace-to-edm', 'edm-takens', 'edm-takens-web', 'shared', 'Models'}
    for item in product.iterdir():
        if item.name in keep_siblings or item.name in keep_root:
            continue
        target = dst_engine / item.name
        if target.exists():
            if item.is_dir():
                safe_rmtree(target)
            else:
                target.unlink()
        if item.is_dir():
            shutil.copytree(item, target, ignore=engine_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
        print(f'  迁移: {item.name} -> trace-engine/{item.name}')


def remove_old_root_after_migration():
    """迁移完成后删除成品目录根下的旧内容。

    保留 trace-engine、trace-engine-web、trace-to-edm、Models、verify_portable.py、sync_product.py 与 README.md，避免先删后写。

    P1 修缮（2026-08-03）: 新增白名单保护 PORTABLE_TECHNICAL_GUIDE.md、
    test_mcp_protocol.py、test_cross_project_http.py 等必需文件，
    原版误删这些文件导致便携目录验证脚手架缺失。
    """
    keep_root = {
        'verify_portable.py', 'sync_product.py', 'README.md',
        # P1 修缮：保护测试脚手架与技术文档
        'PORTABLE_TECHNICAL_GUIDE.md',
        'test_mcp_protocol.py',
        'test_cross_project_http.py',
    }
    keep_siblings = {'trace-engine', 'trace-engine-web', 'trace-to-edm', 'edm-takens', 'edm-takens-web', 'shared', 'Models'}
    for item in product.iterdir():
        if item.name in keep_siblings or item.name in keep_root:
            continue
        if item.is_dir():
            safe_rmtree(item)
        else:
            item.unlink()
        print(f'  清理旧项: {item.name}')


def remove_misplaced_verify_script():
    """删除误同步到 trace-engine/ 下的 verify_portable.py（审计脚本应只在成品根）。"""
    misplaced = dst_engine / 'verify_portable.py'
    if misplaced.exists():
        try:
            misplaced.unlink()
            print(f'  删除误放置项: trace-engine/verify_portable.py')
        except Exception as e:
            print(f'  无法删除 trace-engine/verify_portable.py: {e}')


def remove_legacy_engine_files():
    """删除 trace-engine 子目录下的历史遗留文件（如旧命名 trrace_*.py、误放置的根级 presets.py 等）。"""
    legacy = [
        dst_engine / 'trrace_cli.py',
        dst_engine / 'trrace_loader.py',
        # trace-engine/ 根目录的 presets.py 是旧版 v3 预设文件，
        # 会遮蔽 examples/counterfactual_hybrid/presets.py（含 load_presets），
        # 导致 llama_worker.py ImportError → SUPER 模式启动超时
        dst_engine / 'presets.py',
        # 临时检查脚本，不属于 skill 产物
        dst_engine / '_check_config.py',
    ]
    for f in legacy:
        if f.exists():
            f.unlink()
            print(f'  删除遗留文件: {f.name}')


def cleanup_web_runtime_artifacts(dst: Path):
    """清理成品 trace-engine-web 中的运行时产物，避免增量覆盖遗留旧文件。"""
    patterns = ['web_*_result*.json', 'test_min*.bat', '18)']
    removed = 0
    for pat in patterns:
        for f in dst.glob(pat):
            try:
                if f.is_file():
                    f.unlink()
                    removed += 1
            except Exception as e:
                print(f'  无法删除 {f.name}: {e}')
    for name in ['outputs', 'uploads']:
        d = dst / name
        if d.exists():
            try:
                safe_rmtree(d)
                removed += 1
            except Exception as e:
                print(f'  无法删除 {name}: {e}')
    if removed:
        print(f'  清理运行时产物: {removed} 项')


def copy_data_to_engine():
    """将 TRACE/date 测试数据复制到成品 trace-engine/date，保证独立可运行。"""
    if not src_data.exists():
        print(f'  跳过: 未找到源数据目录 {src_data}')
        return
    dst_data = dst_engine / 'date'
    dst_data.mkdir(parents=True, exist_ok=True)
    for item in src_data.iterdir():
        target = dst_data / item.name
        if target.exists():
            if item.is_dir():
                safe_rmtree(target)
            else:
                target.unlink()
        if item.is_dir():
            shutil.copytree(item, target, ignore=engine_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    print(f'  已同步数据: {dst_data}')


def copy_models_to_engine():
    """将 TRACE/models 下的 LLaMA 训练模型复制到成品 trace-engine/models 与成品根 Models/，
    使 SUPER 模式无需额外下载即可使用，同时满足 trace-to-edm config.py 的便携式布局探测。
    大文件默认跳过 .gitignore 排除项。"""
    # P0 修复 (2026-07-30): 移除硬编码绝对路径，改为基于脚本位置推断 + 环境变量覆盖。
    # 候选顺序: TRACE_SRC_MODELS 环境变量 > _SKILLS_ROOT/Models > _SKILLS_ROOT/trace-engine/Models
    _candidate_models = [
        _SKILLS_ROOT / 'Models',
        _SKILLS_ROOT / 'trace-engine' / 'Models',
        _SKILLS_ROOT / 'trace-engine' / 'models',
    ]
    src_models = Path(os.environ.get('TRACE_SRC_MODELS', ''))
    if not src_models.exists():
        for cand in _candidate_models:
            if cand.exists() and any(cand.iterdir()):
                src_models = cand
                break
    if not src_models.exists() or not any(src_models.iterdir()):
        print(f'  跳过: 未找到源模型目录 (候选: {[str(c) for c in _candidate_models]})')
        return

    # 目标 1: trace-engine/models（引擎内部使用）
    dst_models = dst_engine / 'models'
    dst_models.mkdir(parents=True, exist_ok=True)

    # 目标 2: 成品根 Models/（供 trace-to-edm / config.py 便携式布局探测）
    root_models = product / 'Models'
    root_models.mkdir(parents=True, exist_ok=True)

    for item in src_models.iterdir():
        if not item.is_dir():
            continue
        for dst in [dst_models, root_models]:
            target = dst / item.name
            if target.exists():
                # 仅当目录大小差异较大时才覆盖，避免每次同步都重写大文件
                src_size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                dst_size = sum(f.stat().st_size for f in target.rglob('*') if f.is_file())
                if src_size == dst_size:
                    if dst == dst_models:
                        print(f'  模型已存在且大小一致: {item.name}')
                    continue
                safe_rmtree(target)
            shutil.copytree(item, target, ignore=engine_ignore)
            if dst == dst_models:
                size_mb = sum(f.stat().st_size for f in target.rglob('*') if f.is_file()) / 1e6
                print(f'  已同步模型: {item.name} ({size_mb:.1f} MB)')
    print(f'  已同步模型目录: {dst_models}')
    print(f'  已同步模型目录: {root_models}')


def copy_audit_scripts_to_root():
    """将审计与同步脚本复制到成品根，便于用户直接运行。

    P0 修复 (2026-07-30): 在自包含布局下，sync_product.py 和 verify_portable.py
    可能已在成品根（即脚本所在目录），此时无需复制；在开发布局下从 src_web/work/ 复制。
    """
    # 候选源路径：开发布局 src_web/work/ 或自包含布局 _SCRIPT_DIR
    candidates = {
        'verify_portable.py': [
            src_web / 'work' / 'verify_portable.py',
            _SCRIPT_DIR / 'verify_portable.py',
            _SCRIPT_DIR / 'trace-engine-web' / 'work' / 'verify_portable.py',
        ],
        'sync_product.py': [
            src_web / 'work' / 'sync_product.py',
            _SCRIPT_PATH,  # 脚本自身
            _SCRIPT_DIR / 'sync_product.py',
        ],
    }
    for name, src_candidates in candidates.items():
        target = product / name
        # 如果目标已存在且源就是自身，跳过
        if target.resolve() == _SCRIPT_PATH.resolve():
            print(f'  跳过自复制: {name}')
            continue
        src_path = None
        for cand in src_candidates:
            if cand.exists() and cand.resolve() != target.resolve():
                src_path = cand
                break
        if not src_path:
            print(f'  跳过: 未找到 {name} 的源文件')
            continue
        try:
            shutil.copy2(src_path, target)
            print(f'  已复制审计脚本到成品根: {name}')
        except Exception as e:
            print(f'  无法复制 {name}: {e}')


def cleanup_product_pollution():
    """R44-C 修复 (ROUND44 P0): 同步前清理成品目录所有污染文件.

    病灶 (用户反馈 "你删除了，这个无效文件了吗？为什么我总是说一句你才干一件？"):
      R43 仅修正了 sync_research_reports() 不再同步 META_THINKING,
      但未清理成品目录已存在的污染残留 (Docs/META_THINKING/、__pycache__/).
      且缺少主动清理机制, 导致每次同步后污染仍残留.

    修复策略 (R44 主动清理, 而非被动响应):
      在 main() 开头 (所有同步操作之前) 主动扫描并清理:
      1. Docs/META_THINKING/ 目录 (内部进度归档, 违反"开箱即用"语义)
      2. 所有 ROUND*_META_THINKING.md 文件 (散落的进度归档)
      3. 所有 ROUND*_AUDIT.md 文件 (内部审计报告)
      4. 所有 __pycache__/ 目录 (运行时产物, 违反便携打包约束)
      5. 所有 *.pyc 文件 (运行时产物)

    设计原则: "应清尽清" — 成品目录只包含用户需要的最终产物,
    内部迭代进度保留在工作目录 Docs/META_THINKING/ 即可.
    """
    print('\n[R44] 主动清理成品目录污染文件 (开箱即用语义保障)')
    removed_count = 0

    # 1. 清理 Docs/META_THINKING/ 目录
    docs_meta = product.parent / 'Docs' / 'META_THINKING'
    # 也清理成品目录内部的 Docs/META_THINKING/ (如果存在)
    docs_meta_internal = product / 'Docs' / 'META_THINKING'
    for target in [docs_meta, docs_meta_internal]:
        if target.exists() and target.is_dir():
            try:
                file_count = sum(1 for _ in target.rglob('*') if _.is_file())
                safe_rmtree(target)
                print(f'  [OK] 删除内部进度归档: {target} ({file_count} 个文件)')
                removed_count += file_count
            except Exception as e:
                print(f'  [FAIL] 无法删除 {target}: {e}')

    # 2. 清理所有 ROUND*_META_THINKING.md 和 ROUND*_AUDIT.md 文件
    round_patterns = ['ROUND*_META_THINKING.md', 'ROUND*_AUDIT.md']
    for pattern in round_patterns:
        for f in product.rglob(pattern):
            try:
                f.unlink()
                print(f'  [OK] 删除进度文件: {f.name}')
                removed_count += 1
            except Exception as e:
                print(f'  [FAIL] 无法删除 {f}: {e}')

    # 3. 清理所有 __pycache__/ 目录
    for pycache in product.rglob('__pycache__'):
        if pycache.is_dir():
            try:
                file_count = sum(1 for _ in pycache.iterdir() if _.is_file())
                safe_rmtree(pycache)
                print(f'  [OK] 删除运行时缓存: {pycache} ({file_count} 个文件)')
                removed_count += file_count
            except Exception as e:
                print(f'  [FAIL] 无法删除 {pycache}: {e}')

    # 4. 清理所有 .pyc 文件 (散落的, 不在 __pycache__ 目录中的)
    for pyc in product.rglob('*.pyc'):
        try:
            pyc.unlink()
            print(f'  [OK] 删除运行时文件: {pyc.name}')
            removed_count += 1
        except Exception as e:
            print(f'  [FAIL] 无法删除 {pyc}: {e}')

    if removed_count == 0:
        print('  无污染文件需清理')
    else:
        print(f'  清理完成: 共删除 {removed_count} 项污染文件')


def sync_research_reports():
    """R36-B 修复 (ROUND36 P1): 同步研究汇报到便携目录.

    R43 修正 (ROUND43 P0): 成品目录只保留最终研究成果 (论文),
    不再同步内部进度文件 (ROUND*_META_THINKING.md / ROUND*_AUDIT.md).
    病灶: 原版将开发进度归档 (META_THINKING) 同步到成品目录, 污染了
    成品目录的"开箱即用"语义 — 成品目录应只包含用户需要的最终产物,
    内部迭代进度保留在工作目录 Docs/META_THINKING/ 即可.

    同步内容 (R43 修正后):
      - 五大项目算法模型论文.md (最新版本, 唯一同步项)
    """
    print('\n[R43] 同步研究汇报到便携目录 (仅论文, 不含进度文件)')
    # Docs/ 在开发目录的父级 (研发测试/Docs/)
    src_docs = _SCRIPT_DIR.parent / 'Docs'
    # 研究汇报复制到便携目录根级
    dst_reports = product / '研究汇报'

    if not src_docs.exists():
        print('  Docs/ 目录不存在, 跳过研究汇报同步')
        return

    dst_reports.mkdir(parents=True, exist_ok=True)

    # 论文 (唯一同步项)
    paper_src = src_docs / '五大项目算法模型论文' / '五大项目算法模型论文.md'
    if paper_src.exists():
        shutil.copy2(paper_src, dst_reports / paper_src.name)
        print(f'  ✓ {paper_src.name}')

    # R43 修正: 不再同步 ROUND*_META_THINKING.md 和 ROUND33_F_AUDIT.md
    # 这些是内部进度归档, 保留在工作目录 Docs/META_THINKING/ 即可,
    # 不应污染成品目录的"开箱即用"语义.

    print(f'  研究汇报同步完成: {dst_reports}')


def sync_edm_takens_projects():
    """ROUND28 新增: 同步 EDM-TAKENS 核心库和 Web 项目到便携目录.

    将 Skill/edm-takens (CLI 核心库) 和 Skill/edm-takens-web (Web 服务)
    同步到便携目录下的 edm-takens/ 和 edm-takens-web/ 子目录.

    这是便携目录"开箱即用"要求的关键补充: 科研用户无需访问开发源码树,
    即可在便携目录中直接运行 EDM-TAKENS 的 CLI 和 Web 两种接口.

    同步策略:
      - edm-takens: 全量复制 src/、tests/、docs/、examples/ 及根级配置文件
      - edm-takens-web: 全量复制 backend/、frontend/、docs/、data/ 及根级配置文件
      - 排除 __pycache__、.git、node_modules、运行时输出等产物
    """
    print('\n[ROUND28] 同步 EDM-TAKENS 核心库和 Web 项目')

    # 1. 同步 edm-takens 核心库 (CLI)
    if src_edm_takens.exists():
        print(f'  源: {src_edm_takens}')
        # 删除旧目标后复制 (不保留 node_modules, 因为 edm-takens 是纯 Python)
        if dst_edm_takens.exists():
            try:
                safe_rmtree(dst_edm_takens)
            except PermissionError:
                print(f'  警告: 无法删除旧 {dst_edm_takens.name}, 改为覆盖')
        shutil.copytree(src_edm_takens, dst_edm_takens, ignore=edm_takens_ignore)
        print(f'  已同步 edm-takens 核心库 -> {dst_edm_takens}')

        # 验证关键文件存在性
        edmtakens_critical = [
            dst_edm_takens / 'src' / 'pipeline.py',
            dst_edm_takens / 'src' / 'ccm_causality.py',
            dst_edm_takens / 'src' / 'sovereign_havok.py',
            dst_edm_takens / 'src' / '_numpy_edm.py',
            dst_edm_takens / 'src' / '_numeric_constants.py',
            dst_edm_takens / 'src' / 'surrogate_test.py',
            dst_edm_takens / 'run_pipeline.py',
            dst_edm_takens / 'run_tests.py',
            dst_edm_takens / 'docs' / 'ALGORITHM_AUDIT.md',
        ]
        missing = [str(f.relative_to(product)) for f in edmtakens_critical if not f.exists()]
        if missing:
            print(f'  ⚠ edm-takens 缺失关键文件 ({len(missing)}): {missing}')
        else:
            print(f'  ✓ edm-takens 关键文件齐全 ({len(edmtakens_critical)} 项)')
    else:
        print(f'  跳过: 未找到 edm-takens 源码目录 {src_edm_takens}')

    # 2. 同步 edm-takens-web (Web 服务)
    if src_edm_takens_web.exists():
        print(f'  源: {src_edm_takens_web}')
        # 保留 node_modules (如果已存在), 避免每次重新 npm install
        safe_copytree(src_edm_takens_web, dst_edm_takens_web,
                      edm_takens_web_ignore, preserve=['node_modules'])
        print(f'  已同步 edm-takens-web -> {dst_edm_takens_web}')

        # 验证关键文件存在性
        edmtakens_web_critical = [
            dst_edm_takens_web / 'backend' / 'api.py',
            dst_edm_takens_web / 'backend' / 'sync_check.py',
            dst_edm_takens_web / 'backend' / 'services' / 'summary_builder.py',
            dst_edm_takens_web / 'backend' / 'edmtakens' / 'pipeline.py',
            dst_edm_takens_web / 'backend' / 'edmtakens' / 'ccm_causality.py',
            dst_edm_takens_web / 'frontend' / 'src' / 'main.js',
            dst_edm_takens_web / 'frontend' / 'src' / 'style.css',
            dst_edm_takens_web / 'frontend' / 'index.html',
            dst_edm_takens_web / 'docs' / 'ALGORITHM_AUDIT.md',
            dst_edm_takens_web / 'README.md',
        ]
        missing = [str(f.relative_to(product)) for f in edmtakens_web_critical if not f.exists()]
        if missing:
            print(f'  ⚠ edm-takens-web 缺失关键文件 ({len(missing)}): {missing}')
        else:
            print(f'  ✓ edm-takens-web 关键文件齐全 ({len(edmtakens_web_critical)} 项)')

        # 验证科研披露字段在副本中存在 (S1-5 契约)
        disclosure_check_files = [
            dst_edm_takens_web / 'backend' / 'edmtakens' / 'ccm_causality.py',
            dst_edm_takens_web / 'backend' / 'edmtakens' / '_numpy_edm.py',
        ]
        disclosure_fields = {
            'ccm_causality.py': ['is_strict_confirmatory', 'methodology_disclaimer'],
            '_numpy_edm.py': ['effective_lib_sizes', 'out_of_sample_used'],
        }
        for fpath in disclosure_check_files:
            fname = fpath.name
            if not fpath.exists():
                print(f'  ⚠ 科研披露字段检查跳过: {fname} 不存在')
                continue
            content = fpath.read_text(encoding='utf-8')
            for field in disclosure_fields.get(fname, []):
                if f'"{field}"' not in content and f"'{field}'" not in content:
                    print(f'  ⚠ 科研披露字段缺失: {fname}:{field}')
                # 静默通过, 仅在缺失时报告
        print(f'  ✓ 科研披露字段检查完成 (4 字段)')
    else:
        print(f'  跳过: 未找到 edm-takens-web 源码目录 {src_edm_takens_web}')


def _verify_self_contained_integrity():
    """自包含布局完整性验证：检查关键文件存在性。"""
    critical_files = [
        dst_engine / 'health_check.py',
        dst_engine / 'tests' / 'test_skill.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'six_warriors.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'counterfactual_bridge.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'dowhy_auditor.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'run_real_pipeline.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'causallearn_validator.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'presets.py',
        dst_engine / 'examples' / 'counterfactual_hybrid' / 'presets.yaml',
        dst_web / 'server.js',
        dst_web / 'llama_worker.py',
        dst_web / 'public' / 'js' / 'app.js',
        dst_web / 'public' / 'js' / 'render.js',
        dst_web / 'public' / 'js' / 'jobs.js',
        dst_web / 'public' / 'js' / 'sse.js',
        dst_web / 'services' / 'llamaWorker.js',
        dst_web / 'services' / 'analysis.js',
        dst_web / 'routes' / 'analysis.js',
        dst_web / 'routes' / 'jobs.js',
        dst_web / 'middleware' / 'auth.js',
        # ROUND28 新增: EDM-TAKENS 核心库关键文件
        dst_edm_takens / 'src' / 'pipeline.py',
        dst_edm_takens / 'src' / 'ccm_causality.py',
        dst_edm_takens / 'src' / 'sovereign_havok.py',
        dst_edm_takens / 'src' / '_numpy_edm.py',
        dst_edm_takens / 'src' / '_numeric_constants.py',
        dst_edm_takens / 'src' / 'surrogate_test.py',
        dst_edm_takens / 'run_pipeline.py',
        dst_edm_takens / 'run_tests.py',
        # ROUND28 新增: EDM-TAKENS Web 关键文件
        dst_edm_takens_web / 'backend' / 'api.py',
        dst_edm_takens_web / 'backend' / 'sync_check.py',
        dst_edm_takens_web / 'backend' / 'services' / 'summary_builder.py',
        dst_edm_takens_web / 'backend' / 'edmtakens' / 'pipeline.py',
        dst_edm_takens_web / 'backend' / 'edmtakens' / 'ccm_causality.py',
        dst_edm_takens_web / 'frontend' / 'src' / 'main.js',
        dst_edm_takens_web / 'frontend' / 'src' / 'style.css',
        dst_edm_takens_web / 'frontend' / 'index.html',
        dst_edm_takens_web / 'docs' / 'ALGORITHM_AUDIT.md',
    ]
    missing = []
    for f in critical_files:
        if not f.exists():
            missing.append(str(f.relative_to(product)))
    if missing:
        print(f'  ⚠ 缺失关键文件 ({len(missing)}):')
        for m in missing:
            print(f'    - {m}')
    else:
        print(f'  ✓ 关键文件全部存在 ({len(critical_files)} 项)')

    # 检查模型目录
    models_dir = dst_engine / 'models'
    if models_dir.exists():
        model_names = [d.name for d in models_dir.iterdir() if d.is_dir()]
        print(f'  ✓ 模型目录: {len(model_names)} 个模型 ({", ".join(model_names[:3])}...)')
    else:
        print('  ⚠ 模型目录缺失')

    # 检查无运行时产物污染（work/inputs 和 work/outputs 不应过多）
    work_inputs = dst_web / 'work' / 'inputs'
    work_outputs = dst_web / 'work' / 'outputs'
    if work_inputs.exists():
        n_inputs = len(list(work_inputs.iterdir()))
        if n_inputs > 100:
            print(f'  ⚠ work/inputs 历史文件过多: {n_inputs} 项（建议清理）')
        else:
            print(f'  ✓ work/inputs: {n_inputs} 项')
    if work_outputs.exists():
        n_outputs = len(list(work_outputs.iterdir()))
        if n_outputs > 100:
            print(f'  ⚠ work/outputs 历史文件过多: {n_outputs} 项（建议清理）')
        else:
            print(f'  ✓ work/outputs: {n_outputs} 项')


def main():
    print('=== 同步到成品目录 ===')
    print(f'成品目录: {product}')

    # R44-C 修复 (ROUND44 P0): 同步前主动清理成品目录所有污染文件.
    # 病灶: R43 仅修正了不再同步 META_THINKING, 但未清理已存在的污染残留.
    # 修复: 每次同步前主动扫描并清理 __pycache__、ROUND*_META_THINKING.md、
    #       ROUND*_AUDIT.md、Docs/META_THINKING/ 等污染, 保障"开箱即用"语义.
    cleanup_product_pollution()

    # P1 修复 (2026-07-30 审计): 自包含布局下 src == dst，自我覆盖会导致数据丢失。
    # 自包含布局下仅执行保守清理和验证，跳过所有复制操作。
    # ROUND28 例外: EDM-TAKENS 项目的源 (Skill/) 与目标 (便携目录) 不同,
    # 因此即使在自包含布局下也需同步 EDM-TAKENS 项目.
    if _SELF_CONTAINED:
        print('\n[自包含布局] 检测到成品目录 = 脚本所在目录，仅执行保守清理和验证。')
        print('  跳过: 迁移根内容、覆盖 trace-engine、覆盖 trace-engine-web（避免自我覆盖）')

        # 保守清理：仅删除临时测试文件和遗留产物，不删除用户历史数据
        print('\n[清理] 删除临时测试文件 (.tmp_*.py)')
        tmp_patterns = ['.tmp_*.py', '.tmp_*.js']
        tmp_removed = 0
        for pat in tmp_patterns:
            for f in dst_web.glob(pat):
                try:
                    f.unlink()
                    tmp_removed += 1
                    print(f'  删除: {f.name}')
                except Exception as e:
                    print(f'  无法删除 {f.name}: {e}')
        if tmp_removed == 0:
            print('  无临时文件需清理')

        print('\n[清理] 删除遗留产物 (web_*_result*.json, test_min*.bat)')
        legacy_patterns = ['web_*_result*.json', 'test_min*.bat', '18)']
        legacy_removed = 0
        for pat in legacy_patterns:
            for f in dst_web.glob(pat):
                try:
                    f.unlink()
                    legacy_removed += 1
                    print(f'  删除: {f.name}')
                except Exception as e:
                    print(f'  无法删除 {f.name}: {e}')
        if legacy_removed == 0:
            print('  无遗留产物需清理')

        # 注意: 不删除 work/outputs 和 work/uploads，这些是用户历史数据
        print('\n[保留] work/outputs 和 work/uploads（用户历史数据）')

        print('\n[清理] 清理 trace-engine 遗留文件')
        remove_legacy_engine_files()

        print('\n[清理] 清理成品目录根下旧内容')
        remove_old_root_after_migration()

        # ROUND28 新增: 即使在自包含布局下, 也需同步 EDM-TAKENS 项目
        # 因为 EDM-TAKENS 的源 (Skill/) 与目标 (便携目录) 不同, 不存在自我覆盖风险
        sync_edm_takens_projects()

        # R37-A 修复 (ROUND37 P0): 自包含布局下也需同步研究汇报.
        # 病灶: 原版 main() 在自包含布局下 early return, 跳过 sync_research_reports()
        # 调用 (line 794), 导致便携目录根级 研究汇报/ 文件夹永远为空.
        # 修复: 在 early return 之前显式调用 sync_research_reports().
        sync_research_reports()

        print('\n[验证] 检查关键文件存在性')
        _verify_self_contained_integrity()

        print('\n=== 自包含布局清理完成 ===')
        print(f'trace-engine  -> {dst_engine}')
        print(f'trace-engine-web -> {dst_web}')
        print(f'edm-takens    -> {dst_edm_takens}')
        print(f'edm-takens-web -> {dst_edm_takens_web}')
        print('提示: 若需从开发布局同步到独立便携目录，请设置 TRACE_PRODUCT_DIR 环境变量。')
        return

    # 1. 迁移现有成品根内容到 trace-engine/
    print('\n[1/5] 迁移现有成品根内容到 trace-engine/')
    copy_existing_root_to_engine()

    # 1.5 复制审计脚本到成品根
    print('\n[1.5/5] 复制审计脚本到成品根')
    copy_audit_scripts_to_root()

    # 2. 用工作副本覆盖/更新 trace-engine/
    print('\n[2/5] 同步 trace-engine 最新代码')
    # 保留模型（较大），只覆盖代码和元数据
    for item in src_engine.iterdir():
        target = dst_engine / item.name
        if item.is_dir() and item.name in ('examples', 'references', 'tests'):
            safe_copytree(item, target, engine_ignore)
            print(f'  覆盖: {item.name}')
        elif item.is_file():
            # 不覆盖模型文件（大）
            if item.suffix in ('.safetensors', '.bin', '.pt', '.ckpt'):
                continue
            if target.exists():
                target.unlink()
            shutil.copy2(item, target)
            print(f'  覆盖: {item.name}')

    # 3. 同步测试数据
    print('\n[3/5] 同步 TRACE/date 测试数据')
    copy_data_to_engine()

    # 3.5 同步 LLaMA 训练模型
    print('\n[3.5/5] 同步 TRACE/models 训练模型')
    copy_models_to_engine()

    # 3.6 清理历史遗留文件
    print('\n[3.6/5] 清理 trace-engine 遗留文件')
    remove_legacy_engine_files()

    # 4. 同步 trace-engine-web（保留 node_modules 避免每次重新 npm install）
    print('\n[4/5] 同步 trace-engine-web')
    cleanup_web_runtime_artifacts(dst_web)
    safe_copytree(src_web, dst_web, web_ignore, preserve=['node_modules'])
    print(f'  已同步: {dst_web}')

    # 5. 清理旧根内容
    print('\n[5/5] 清理成品目录根下旧内容')
    remove_old_root_after_migration()

    # 6. 复制便携目录审计脚本到成品根
    print('\n[6/5] 复制独立运行审计脚本')
    verify_candidates = [
        src_web / 'work' / 'verify_portable.py',
        _SCRIPT_DIR / 'verify_portable.py',
        _SCRIPT_DIR / 'trace-engine-web' / 'work' / 'verify_portable.py',
    ]
    verify_dst = product / 'verify_portable.py'
    verify_copied = False
    for cand in verify_candidates:
        if cand.exists() and cand.resolve() != verify_dst.resolve():
            shutil.copy2(cand, verify_dst)
            print(f'  已复制: {verify_dst} (from {cand})')
            verify_copied = True
            break
    if not verify_copied:
        print(f'  未找到 verify_portable.py (候选: {[str(c) for c in verify_candidates]})')

    # 6.5 复制成品根 README
    print('\n[6.5/5] 复制成品根 README')
    readme_candidates = [
        src_web / 'work' / 'README_PRODUCT.md',
        _SCRIPT_DIR / 'README_PRODUCT.md',
        _SCRIPT_DIR / 'trace-engine-web' / 'work' / 'README_PRODUCT.md',
    ]
    readme_dst = product / 'README.md'
    readme_copied = False
    for cand in readme_candidates:
        if cand.exists() and cand.resolve() != readme_dst.resolve():
            shutil.copy2(cand, readme_dst)
            print(f'  已复制: {readme_dst} (from {cand})')
            readme_copied = True
            break
    if not readme_copied:
        print(f'  未找到 README_PRODUCT.md (候选: {[str(c) for c in readme_candidates]})')

    # 6.6 清理误放置的审计脚本副本
    print('\n[6.6/5] 清理误放置的审计脚本副本')
    remove_misplaced_verify_script()

    # ROUND28 新增: 同步 EDM-TAKENS 核心库和 Web 项目
    sync_edm_takens_projects()

    # R36-B 修复 (ROUND36 P1): 同步研究汇报到便携目录
    sync_research_reports()

    print('\n=== 同步完成 ===')
    print(f'trace-engine  -> {dst_engine}')
    print(f'trace-engine-web -> {dst_web}')
    print(f'edm-takens    -> {dst_edm_takens}')
    print(f'edm-takens-web -> {dst_edm_takens_web}')
    print(f'审计脚本 -> {verify_dst}')
    print(f'成品 README -> {readme_dst}')


def stop_stale_servers():
    """调用 stop_servers.ps1 结束可能锁定成品目录的 stale 服务。"""
    ps1 = src_web / 'stop_servers.ps1'
    if not ps1.exists():
        print('  未找到 stop_servers.ps1，跳过进程清理')
        return
    print('  正在结束可能锁定目录的 stale 服务...')
    try:
        import subprocess
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps1)],
                       check=False, capture_output=True, text=True)
    except Exception as e:
        print(f'  结束 stale 服务时出错: {e}')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='同步 trace-engine 与 trace-engine-web 到成品目录')
    parser.add_argument('--force-stop', action='store_true',
                        help='同步前先结束可能锁定成品目录的 stale Node 服务')
    parser.add_argument('--product', type=str, default=None,
                        help='成品目录路径（覆盖环境变量 TRACE_PRODUCT_DIR 与自动探测）')
    args = parser.parse_args()
    if args.product:
        product = Path(args.product)
        print(f'[CLI] 使用命令行参数覆盖成品目录: {product}')
    if args.force_stop:
        stop_stale_servers()
    main()
