#!/usr/bin/env python3
"""
重置数据库脚本
清理所有表并重新初始化数据库
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app import models  # noqa: F401 - 确保所有模型被导入
from app.core.settings import settings


async def drop_all_tables():
    """删除所有表"""
    print("🗑️  正在删除所有表...")

    # 使用同步 URL 来执行 DDL 操作
    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )

    async with engine.begin() as conn:
        # 禁用外键检查（PostgreSQL 使用 CASCADE）
        await conn.execute(text("SET session_replication_role = 'replica';"))

        # 获取所有表名
        result = await conn.execute(text("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
        """))
        tables = [row[0] for row in result.fetchall()]

        if tables:
            print(f"📋 找到 {len(tables)} 个表: {', '.join(tables)}")
            # 删除所有表（CASCADE 会自动处理外键）
            for table in tables:
                await conn.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE;'))
            print(f"✅ 已删除 {len(tables)} 个表")
        else:
            print("ℹ️  数据库中没有表")

        # 删除所有枚举类型
        result = await conn.execute(text("""
            SELECT typname
            FROM pg_type
            WHERE typtype = 'e'
            AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        """))
        enums = [row[0] for row in result.fetchall()]

        if enums:
            print(f"📋 找到 {len(enums)} 个枚举类型: {', '.join(enums)}")
            for enum in enums:
                await conn.execute(text(f'DROP TYPE IF EXISTS "{enum}" CASCADE;'))
            print(f"✅ 已删除 {len(enums)} 个枚举类型")

        # 恢复外键检查
        await conn.execute(text("SET session_replication_role = 'origin';"))

    await engine.dispose()
    print("✅ 数据库清理完成")


async def run_migrations():
    """运行数据库迁移"""
    print("\n🚀 正在运行数据库迁移...")

    import subprocess

    # 设置工作目录
    work_dir = project_root

    # 运行 alembic upgrade head
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        print("✅ 数据库迁移完成")
        if result.stdout:
            print(result.stdout)
        return True
    else:
        print("❌ 数据库迁移失败")
        if result.stderr:
            print(result.stderr)
        if result.stdout:
            print(result.stdout)
        return False


async def main():
    """主函数"""
    import sys

    print("=" * 50)
    print("🔄 重置数据库（清理 + 重建）")
    print("=" * 50)
    print()

    # 检查是否有 --force 参数
    force = '--force' in sys.argv or '-f' in sys.argv

    if not force:
        # 确认操作
        print("⚠️  警告：此操作将：")
        print("   1. 删除所有表和数据")
        print("   2. 删除所有枚举类型")
        print("   3. 重新运行数据库迁移")
        print()

        try:
            response = input("确认继续？(yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("❌ 操作已取消")
                return
        except EOFError:
            print("❌ 非交互式环境，请使用 --force 参数")
            print("   用法: python scripts/reset_database.py --force")
            sys.exit(1)

    try:
        # 1. 删除所有表
        await drop_all_tables()

        # 2. 运行迁移
        success = await run_migrations()

        if success:
            print("\n" + "=" * 50)
            print("✅ 数据库重置完成！")
            print("=" * 50)
        else:
            print("\n" + "=" * 50)
            print("❌ 数据库重置失败，请检查错误信息")
            print("=" * 50)
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

