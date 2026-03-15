#!/usr/bin/env python3
"""数据库初始化脚本，用于在运行迁移前确保表已创建。"""
import asyncio
import sys


async def main():
    """初始化数据库表结构。"""
    try:
        from daiflow.database import init_db
        from daiflow.config import init_daiflow_dir

        # 确保数据目录存在
        init_daiflow_dir()

        # 创建所有表（如果已存在则跳过）
        await init_db()

        print("[init-db] Database tables initialized successfully")
        return 0
    except Exception as e:
        print(f"[init-db] Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
