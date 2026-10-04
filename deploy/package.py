# -*- coding: utf-8 -*-
"""把项目打包成可以直接上传到服务器的 tar.gz。

    python deploy/package.py              # 用已有的 frontend/dist
    python deploy/package.py --build      # 先跑 npm run build 再打包
    python deploy/package.py --with-db    # 连 whatsapp.db 一起打（会把现有数据带上去）

产物： dist-deploy/whatsapp-system-YYYYmmdd-HHMM.tar.gz
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_DIR / "dist-deploy"

# 要打进包里的文件/目录（相对项目根）
INCLUDE_FILES = [
    "main.py",
    "tenancy.py",
    "tenant_api.py",
    "backup.py",
    "operations.py",
    "service_config.py",
    "service_api.py",
    "resource_api.py",
    "finance_api.py",
    "account_export_api.py",
    "account_management_api.py",
    "workspace_api.py",
    "whatsapp_session.py",
    "connect_whatsapp.py",
    "requirements.txt",
    "README.md",
    "env.example.ps1",
]
INCLUDE_DIRS = [
    "providers",
    "deploy",
    "docs",
    "tools",
    "tests",
    "frontend/dist",
]

# 明确排除
EXCLUDE_PATTERNS = (
    "__pycache__", ".pyc", ".pyo", ".pytest_cache",
    "node_modules", ".git", ".cowork-temp", "dist-deploy",
    "whatsapp_auth", "qr.png", ".env", ".venv", "venv",
    "*.log", ".DS_Store",
)


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    for pat in EXCLUDE_PATTERNS:
        if pat.startswith("*"):
            if path.name.endswith(pat[1:]):
                return True
        elif pat in parts or path.name == pat:
            return True
    return False


def build_frontend() -> bool:
    frontend = PROJECT_DIR / "frontend"
    if not (frontend / "node_modules").is_dir():
        print("  frontend/node_modules 不存在，先跑 npm install ...")
        r = subprocess.run("npm install", cwd=frontend, shell=True)
        if r.returncode != 0:
            return False
    print("  执行 npm run build ...")
    r = subprocess.run("npm run build", cwd=frontend, shell=True)
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="打包部署文件")
    ap.add_argument("--build", action="store_true", help="先构建前端")
    ap.add_argument("--with-db", action="store_true", help="带上 whatsapp.db（含现有数据）")
    args = ap.parse_args()

    print("=" * 60)
    print(" 打包 WhatsApp 群发系统")
    print("=" * 60)

    if args.build:
        print("[1/3] 构建前端")
        if not build_frontend():
            print("  前端构建失败，中止")
            return 1
    else:
        print("[1/3] 跳过前端构建（用现有 dist）")

    dist_index = PROJECT_DIR / "frontend" / "dist" / "index.html"
    if not dist_index.is_file():
        print(f"  [警告] 没找到 {dist_index}")
        print("         服务器上会没有页面。加 --build 重新构建。")

    stamp = time.strftime("%Y%m%d-%H%M")
    name = f"whatsapp-system-{stamp}"
    OUT_DIR.mkdir(exist_ok=True)
    tarball = OUT_DIR / f"{name}.tar.gz"

    print("[2/3] 收集文件")
    added = 0
    with tarfile.open(tarball, "w:gz") as tar:
        def add(path: Path, arcname: str):
            nonlocal added
            if not path.exists() or should_skip(path):
                return
            tar.add(path, arcname=arcname, recursive=False)
            if path.is_file():
                added += 1
            else:
                for child in sorted(path.iterdir()):
                    add(child, f"{arcname}/{child.name}")

        for f in INCLUDE_FILES:
            add(PROJECT_DIR / f, f"{name}/{f}")
        for d in INCLUDE_DIRS:
            add(PROJECT_DIR / d, f"{name}/{d}")

        if args.with_db:
            db = PROJECT_DIR / "whatsapp.db"
            if db.is_file():
                tar.add(db, arcname=f"{name}/whatsapp.db")
                print(f"  已包含数据库 whatsapp.db（{db.stat().st_size/1024:.0f} KB）")
            else:
                print("  [警告] 没找到 whatsapp.db")

    size_mb = tarball.stat().st_size / 1048576
    print(f"[3/3] 完成")
    print()
    print(f"  产物 : {tarball}")
    print(f"  大小 : {size_mb:.1f} MB")
    print(f"  文件 : {added} 个")
    print()
    print(" 上传后在服务器上执行：")
    print(f"   tar -xzf {tarball.name} -C /www/wwwroot/")
    print(f"   cd /www/wwwroot/{name}")
    print( "   bash deploy/server/install.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
