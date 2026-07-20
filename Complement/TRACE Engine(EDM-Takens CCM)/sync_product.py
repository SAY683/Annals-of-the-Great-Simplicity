"""
将 trace-engine 与 trace-engine-web 同步到成品目录，并重新整理为子目录结构。
排除运行时产物（outputs, __pycache__, .git, node_modules, work 等）。

路径可通过环境变量覆盖，默认保持与原始开发目录一致：
  TRACE_PRODUCT_DIR  -> 成品目录
  TRACE_SRC_ENGINE   -> trace-engine 源码目录
  TRACE_SRC_WEB      -> trace-engine-web 源码目录
  TRACE_SRC_DATA     -> 测试数据目录
"""
import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

# 成品目录（硬编码 fallback）
# 注意：迁移机器需通过环境变量 TRACE_PRODUCT_DIR 或命令行参数 --product 覆盖
_DEFAULT_PRODUCT_DIR = r'G:\git\Annals-of-the-Great-Simplicity-main\Annals-of-the-Great-Simplicity\Complement\TRACE Engine(EDM-Takens CCM)'

_env_product = os.environ.get('TRACE_PRODUCT_DIR')
if _env_product:
    product = Path(_env_product)
else:
    product = Path(_DEFAULT_PRODUCT_DIR)
    warnings.warn(
        f'TRACE_PRODUCT_DIR 环境变量未设置，使用硬编码 fallback: {product}. '
        '迁移机器需通过环境变量 TRACE_PRODUCT_DIR 或命令行参数 --product 覆盖。',
        stacklevel=2,
    )

src_engine = Path(os.environ.get('TRACE_SRC_ENGINE', r'F:\攻略\研发测试\.skills\trace-engine'))
src_web = Path(os.environ.get('TRACE_SRC_WEB', r'F:\攻略\研发测试\.skills\trace-engine-web'))
src_data = Path(os.environ.get('TRACE_SRC_DATA', r'F:\攻略\研发测试\TRACE\date'))

dst_engine = product / 'trace-engine'
dst_web = product / 'trace-engine-web'

# 运行时产物排除模式
engine_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    'outputs', 'work', 'node_modules', 'package-lock.json'
)
web_ignore = shutil.ignore_patterns(
    '__pycache__', '*.pyc', '*.pyo', '.git', '.gitignore',
    'node_modules', 'package-lock.json', 'work', 'outputs',
    'uploads', 'web_*_result*.json', 'test_min*.bat', '18)'
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
    keep_siblings = {'trace-engine', 'trace-engine-web', 'trace-to-edm', 'Models'}
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
    """
    keep_root = {'verify_portable.py', 'sync_product.py', 'README.md'}
    keep_siblings = {'trace-engine', 'trace-engine-web', 'trace-to-edm', 'Models'}
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
    src_models = Path(os.environ.get('TRACE_SRC_MODELS', r'F:\攻略\研发测试\TRACE\models'))
    if not src_models.exists():
        print(f'  跳过: 未找到源模型目录 {src_models}')
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
    """将 work/ 下的审计与同步脚本复制到成品根，便于用户直接运行。"""
    scripts = {
        'verify_portable.py': src_web / 'work' / 'verify_portable.py',
        'sync_product.py': src_web / 'work' / 'sync_product.py',
    }
    for name, src_path in scripts.items():
        if not src_path.exists():
            print(f'  跳过: 未找到 {src_path}')
            continue
        target = product / name
        try:
            shutil.copy2(src_path, target)
            print(f'  已复制审计脚本到成品根: {name}')
        except Exception as e:
            print(f'  无法复制 {name}: {e}')


def main():
    print('=== 同步到成品目录 ===')
    print(f'成品目录: {product}')

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
    verify_src = src_web / 'work' / 'verify_portable.py'
    verify_dst = product / 'verify_portable.py'
    if verify_src.exists():
        shutil.copy2(verify_src, verify_dst)
        print(f'  已复制: {verify_dst}')
    else:
        print(f'  未找到 {verify_src}')

    # 6.5 复制成品根 README
    print('\n[6.5/5] 复制成品根 README')
    readme_src = src_web / 'work' / 'README_PRODUCT.md'
    readme_dst = product / 'README.md'
    if readme_src.exists():
        shutil.copy2(readme_src, readme_dst)
        print(f'  已复制: {readme_dst}')
    else:
        print(f'  未找到 {readme_src}')

    # 6.6 清理误放置的审计脚本副本
    print('\n[6.6/5] 清理误放置的审计脚本副本')
    remove_misplaced_verify_script()

    print('\n=== 同步完成 ===')
    print(f'trace-engine  -> {dst_engine}')
    print(f'trace-engine-web -> {dst_web}')
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
                        help='成品目录路径（覆盖环境变量 TRACE_PRODUCT_DIR 与硬编码 fallback）')
    args = parser.parse_args()
    if args.product:
        product = Path(args.product)
        print(f'[CLI] 使用命令行参数覆盖成品目录: {product}')
    if args.force_stop:
        stop_stale_servers()
    main()
