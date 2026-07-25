"""
将 shared/ 下的共享资源复制到三大 Web 项目的本地 shared/ 目录，
确保开发和便携环境中引用路径一致。
"""
import shutil
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent
SHARED = SKILLS / "shared"

TARGETS = [
    SKILLS / "trace-engine-web" / "public" / "shared",
    SKILLS / "trace-to-edm" / "public" / "shared",
    SKILLS / "edm-takens-web" / "frontend" / "shared",
]

print("=" * 60)
print("同步共享资源到各项目本地 shared/ 目录")
print("=" * 60)

for dst in TARGETS:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SHARED, dst)
    rel = dst.relative_to(SKILLS)
    print(f"  [OK] {rel}")

print("\n完成")
