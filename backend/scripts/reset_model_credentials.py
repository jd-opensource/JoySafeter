"""
重置模型凭据表（model_credential）的脚本。

使用场景：
- 之前未在环境变量中固定 `CREDENTIAL_ENCRYPTION_KEY`/`ENCRYPTION_KEY`，导致每次重启随机生成密钥；
- 旧密钥已经遗失，历史加密的模型凭据无法解密，导致默认模型 / 模型加载失败。

本脚本会在**确认模式**下清空 `model_credential` 表中的所有记录，以便在配置好新的固定密钥后重新在前端录入模型凭据。

⚠️ 风险提示：
- 本脚本会删除所有模型凭据记录（仅限 `model_credential` 表），但不会删除模型供应商和模型实例配置；
- 删除之后，历史凭据无法恢复，但在密钥遗失的情况下，本身也已经无法解密。
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.settings import settings


def _mask_database_url(url: str | None) -> str:
    """简单脱敏数据库 URL（隐藏密码部分）"""
    if not url:
        return "<unknown>"
    # 例如：postgresql+asyncpg://user:password@host:port/db
    try:
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        # user:password@host...
        if "@" not in rest or ":" not in rest.split("@", 1)[0]:
            return f"{scheme}://***@{rest.split('@', 1)[-1]}" if "@" in rest else f"{scheme}://{rest}"
        auth, tail = rest.split("@", 1)
        user = auth.split(":", 1)[0]
        return f"{scheme}://{user}:***@{tail}"
    except Exception:
        return "<masked>"


async def reset_model_credentials(dry_run: bool = True) -> None:
    """
    重置 model_credential 表。

    - dry_run=True：仅预览将要删除的记录数，不执行删除；
    - dry_run=False：实际删除所有记录。
    """
    key = getattr(settings, "credential_encryption_key", None)
    if not key:
        print(
            "[ERROR] credential_encryption_key 未配置。\n"
            "请先在环境变量或 .env 中设置 CREDENTIAL_ENCRYPTION_KEY（或别名 ENCRYPTION_KEY），"
            "并确保后续不再修改该值。"
        )
        return

    # 仅从环境变量中读取数据库 URL（不依赖 settings），用于日志展示
    import os

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        # 如果未直接配置 DATABASE_URL，则根据 POSTGRES_* 环境变量拼接
        user = os.getenv("POSTGRES_USER", "")
        password = os.getenv("POSTGRES_PASSWORD", "")
        host = os.getenv("POSTGRES_HOST", "")
        port = os.getenv("POSTGRES_PORT", "")
        db_name = os.getenv("POSTGRES_DB", "")
        if all([user, host, port, db_name]):
            if password:
                db_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"
            else:
                db_url = f"postgresql+asyncpg://{user}@{host}:{port}/{db_name}"
        else:
            db_url = None

    masked_db_url = _mask_database_url(db_url)
    print(f"[INFO] 当前数据库连接（脱敏）: {masked_db_url}")

    async with AsyncSessionLocal() as session:
        # 使用原生 SQL，避免触发全部 ORM mapper 初始化（绕过 UserSandbox 相关依赖）
        result = await session.execute(text("SELECT COUNT(*) FROM model_credential"))
        total: int = result.scalar_one()
        print(f"[INFO] 当前 model_credential 记录数: {total}")

        if dry_run:
            print("[DRY-RUN] 预览模式：不会执行任何删除操作。")
            print("[DRY-RUN] 如果继续执行实际重置，将删除上述所有模型凭据记录。")
            return

        if total == 0:
            print("[INFO] model_credential 表当前为空，无需删除。")
            return

        print(
            "[WARN] 即将删除所有模型凭据记录（model_credential 表）。\n"
            "       此操作不可恢复，但由于旧密钥已遗失，原有加密数据本身也无法解密。\n"
            "       删除后需要在前端重新配置各模型的 API 密钥等凭据。"
        )

        await session.execute(text("DELETE FROM model_credential"))
        await session.commit()

        print("[DONE] 已清空 model_credential 表。")
        print("[NEXT] 请在前端管理界面重新配置各模型供应商的凭据，并设置默认模型。")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("重置模型凭据表（model_credential）。默认以 dry-run 预览模式运行，使用 --force 执行实际删除。")
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览将要删除的记录数（默认行为）。",
    )
    group.add_argument(
        "--force",
        action="store_true",
        help="执行实际删除操作，清空 model_credential 表。",
    )
    return parser.parse_args(argv)


async def _async_main(args: argparse.Namespace) -> None:
    # 默认 dry-run，除非显式指定 --force
    dry_run = not args.force
    if args.dry_run:
        dry_run = True

    mode = "DRY-RUN (预览)" if dry_run else "FORCE (实际删除)"
    print(f"[INFO] 运行模式: {mode}")

    await reset_model_credentials(dry_run=dry_run)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
