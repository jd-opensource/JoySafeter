#!/usr/bin/env python3
"""
清空 model_credential 和 model_instance 表
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.settings import settings  # noqa: E402


async def clear_model_tables():
    """清空 model_credential 和 model_instance 表"""
    print("🗑️  正在清空 model_credential 和 model_instance 表...")

    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )

    try:
        async with engine.begin() as conn:
            # 先获取记录数
            result = await conn.execute(text("SELECT COUNT(*) FROM model_credential"))
            credential_count = result.scalar()

            result = await conn.execute(text("SELECT COUNT(*) FROM model_instance"))
            instance_count = result.scalar()

            print("📊 当前记录数:")
            print(f"   - model_credential: {credential_count} 条")
            print(f"   - model_instance: {instance_count} 条")

            if credential_count == 0 and instance_count == 0:
                print("ℹ️  表已经是空的，无需清空")
                return

            # 清空表（使用 TRUNCATE 更快，且会重置自增序列）
            # CASCADE 确保处理外键约束
            await conn.execute(text("TRUNCATE TABLE model_credential CASCADE"))
            print("✅ 已清空 model_credential 表")

            await conn.execute(text("TRUNCATE TABLE model_instance CASCADE"))
            print("✅ 已清空 model_instance 表")

            print(f"\n✅ 成功清空 {credential_count + instance_count} 条记录")

    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        await engine.dispose()


async def main():
    """主函数"""
    print("=" * 50)
    print("🔄 清空 model_credential 和 model_instance 表")
    print("=" * 50)
    print()

    # 检查是否有 --force 参数
    force = "--force" in sys.argv or "-f" in sys.argv

    if not force:
        # 确认操作
        print("⚠️  警告：此操作将清空以下表的所有数据：")
        print("   - model_credential")
        print("   - model_instance")
        print()

        try:
            response = input("确认继续？(yes/no): ")
            if response.lower() not in ["yes", "y"]:
                print("❌ 操作已取消")
                return
        except EOFError:
            print("❌ 非交互式环境，请使用 --force 参数")
            print("   用法: python scripts/clear_model_tables.py --force")
            sys.exit(1)

    try:
        await clear_model_tables()

        print("\n" + "=" * 50)
        print("✅ 操作完成！")
        print("=" * 50)

    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
