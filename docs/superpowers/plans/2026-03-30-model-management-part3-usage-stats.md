# 模型管理重构 Part 3：使用量统计系统

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增模型调用使用量统计系统，包括后端日志采集、聚合查询 API、前端统计 Tab（摘要卡片 + 趋势图 + 模型排行）。

**Architecture:** 后端新增 model_usage_log 表 + Repository + Service + API。采集点在 ModelService 层显式调用，不侵入 core/model。前端新增 recharts 依赖用于趋势图。

**Tech Stack:** FastAPI / SQLAlchemy async / Alembic / React 19 / TypeScript / recharts / Tailwind

**Spec:** `docs/superpowers/specs/2026-03-30-model-management-refactor-design.md` Section 5

**前置依赖：** Part 1 计划完成（Master-Detail 布局 + detail-panel Tab 骨架已就位）

---

## File Structure

### 后端新增

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `backend/app/models/model_usage_log.py` | 使用量日志 ORM 模型 |
| Create | `backend/alembic/versions/20260330_000001_add_model_usage_log.py` | 迁移脚本 |
| Create | `backend/app/repositories/model_usage_log.py` | 日志 Repository（含聚合查询） |
| Create | `backend/app/services/model_usage_service.py` | 采集 + 聚合 Service |
| Create | `backend/app/api/v1/model_usage.py` | 使用量统计 API |
| Modify | `backend/app/services/model_service.py` | 在调用链路中插入日志采集 |

### 前端新增

| 操作 | 文件 | 职责 |
|------|------|------|
| Create | `frontend/app/settings/models/components/detail-panel/stats-tab/summary-cards.tsx` | 摘要卡片行 |
| Create | `frontend/app/settings/models/components/detail-panel/stats-tab/usage-chart.tsx` | 趋势图 + 模型排行 |
| Create | `frontend/app/settings/models/components/detail-panel/stats-tab/stats-tab.tsx` | 统计 Tab 容器 |
| Modify | `frontend/hooks/queries/models.ts` | 新增 useModelUsageStats hook |
| Modify | `frontend/types/models.ts` | 新增统计相关类型 |

### 测试

| 文件 | 覆盖 |
|------|------|
| `backend/tests/test_model_usage_api.py` | 统计查询、过滤、空数据 |
| `backend/tests/test_model_usage_service.py` | 日志采集、聚合计算 |
| `frontend/app/settings/models/__tests__/stats-tab.test.tsx` | 空状态、摘要卡片、时间范围切换 |

---

## Task 1: ORM 模型 + Alembic 迁移

**Files:**
- Create: `backend/app/models/model_usage_log.py`
- Create: `backend/alembic/versions/20260330_000001_add_model_usage_log.py`

- [ ] **Step 1: 创建 ORM 模型**

创建 `backend/app/models/model_usage_log.py`：

```python
"""
模型调用日志模型
"""

from typing import Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ModelUsageLog(BaseModel):
    """模型调用日志表"""

    __tablename__ = "model_usage_log"

    provider_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="供应商名称"
    )
    model_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="模型名称"
    )
    model_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="chat", comment="模型类型"
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        comment="调用用户",
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="输入 token 数"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="输出 token 数"
    )
    total_time_ms: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="总响应时间（毫秒）"
    )
    ttft_ms: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="首 token 延迟（毫秒）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success", comment="success / error"
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True, comment="错误信息"
    )
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="chat", comment="调用来源：playground / chat / agent"
    )

    __table_args__ = (
        Index("model_usage_log_created_at_idx", "created_at"),
        Index("model_usage_log_provider_model_idx", "provider_name", "model_name"),
        Index("model_usage_log_composite_idx", "created_at", "provider_name", "model_name"),
    )
```

- [ ] **Step 2: 在 models/__init__.py 中注册（如有）**

检查 `backend/app/models/__init__.py`，如果有显式导入列表则加入 `ModelUsageLog`。

- [ ] **Step 3: 创建迁移脚本**

创建 `backend/alembic/versions/20260330_000001_add_model_usage_log.py`，down_revision 指向 Task 1 Part 1 的迁移 `j0k1l2m3n4o5`。

```python
"""add model_usage_log table

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_usage_log",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_name", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False, server_default="chat"),
        sa.Column("user_id", sa.String(255), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_time_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("ttft_ms", sa.Float, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="chat"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("model_usage_log_created_at_idx", "model_usage_log", ["created_at"])
    op.create_index("model_usage_log_provider_model_idx", "model_usage_log", ["provider_name", "model_name"])
    op.create_index("model_usage_log_composite_idx", "model_usage_log", ["created_at", "provider_name", "model_name"])


def downgrade() -> None:
    op.drop_table("model_usage_log")
```

- [ ] **Step 4: 运行迁移**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/model_usage_log.py backend/alembic/versions/20260330_000001_add_model_usage_log.py
git commit -m "feat: add model_usage_log table and migration"
```

---

## Task 2: Repository — 日志写入 + 聚合查询

**Files:**
- Create: `backend/app/repositories/model_usage_log.py`

- [ ] **Step 1: 创建 repository**

```python
"""
ModelUsageLog Repository
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_usage_log import ModelUsageLog

from .base import BaseRepository


class ModelUsageLogRepository(BaseRepository[ModelUsageLog]):
    def __init__(self, db: AsyncSession):
        super().__init__(ModelUsageLog, db)

    async def get_summary(
        self,
        since: datetime,
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取聚合摘要"""
        conditions = [ModelUsageLog.created_at >= since]
        if provider_name:
            conditions.append(ModelUsageLog.provider_name == provider_name)
        if model_name:
            conditions.append(ModelUsageLog.model_name == model_name)

        query = select(
            func.count().label("total_calls"),
            func.sum(ModelUsageLog.input_tokens).label("total_input_tokens"),
            func.sum(ModelUsageLog.output_tokens).label("total_output_tokens"),
            func.avg(ModelUsageLog.total_time_ms).label("avg_response_time_ms"),
            func.sum(
                func.cast(ModelUsageLog.status == "error", sa.Integer)
            ).label("error_count"),
        ).where(and_(*conditions))

        result = await self.db.execute(query)
        row = result.one()

        total_calls = row.total_calls or 0
        error_count = row.error_count or 0

        return {
            "total_calls": total_calls,
            "total_input_tokens": row.total_input_tokens or 0,
            "total_output_tokens": row.total_output_tokens or 0,
            "avg_response_time_ms": round(row.avg_response_time_ms or 0, 1),
            "error_rate": round(error_count / total_calls, 4) if total_calls > 0 else 0,
        }

    async def get_timeline(
        self,
        since: datetime,
        granularity: str = "hour",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取时序数据"""
        conditions = [ModelUsageLog.created_at >= since]
        if provider_name:
            conditions.append(ModelUsageLog.provider_name == provider_name)
        if model_name:
            conditions.append(ModelUsageLog.model_name == model_name)

        if granularity == "hour":
            time_bucket = func.date_trunc("hour", ModelUsageLog.created_at)
        else:
            time_bucket = func.date_trunc("day", ModelUsageLog.created_at)

        query = (
            select(
                time_bucket.label("timestamp"),
                func.count().label("calls"),
                func.sum(ModelUsageLog.input_tokens + ModelUsageLog.output_tokens).label("tokens"),
                func.avg(ModelUsageLog.total_time_ms).label("avg_time_ms"),
            )
            .where(and_(*conditions))
            .group_by(time_bucket)
            .order_by(time_bucket)
        )

        result = await self.db.execute(query)
        return [
            {
                "timestamp": row.timestamp.isoformat(),
                "calls": row.calls,
                "tokens": row.tokens or 0,
                "avg_time_ms": round(row.avg_time_ms or 0, 1),
            }
            for row in result.all()
        ]

    async def get_by_model(
        self,
        since: datetime,
        provider_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """按模型分组统计"""
        conditions = [ModelUsageLog.created_at >= since]
        if provider_name:
            conditions.append(ModelUsageLog.provider_name == provider_name)

        query = (
            select(
                ModelUsageLog.model_name,
                func.count().label("calls"),
                func.sum(ModelUsageLog.input_tokens + ModelUsageLog.output_tokens).label("tokens"),
            )
            .where(and_(*conditions))
            .group_by(ModelUsageLog.model_name)
            .order_by(func.count().desc())
        )

        result = await self.db.execute(query)
        return [
            {
                "model_name": row.model_name,
                "calls": row.calls,
                "tokens": row.tokens or 0,
            }
            for row in result.all()
        ]

    async def cleanup_old_logs(self, days: int = 90) -> int:
        """清理过期日志，返回删除行数"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        from sqlalchemy import delete

        result = await self.db.execute(
            delete(ModelUsageLog).where(ModelUsageLog.created_at < cutoff)
        )
        return result.rowcount
```

注意：`get_summary` 中的 `sa.Integer` 需要 `import sqlalchemy as sa`，在文件顶部加上。

- [ ] **Step 2: Commit**

```bash
git add backend/app/repositories/model_usage_log.py
git commit -m "feat: add model_usage_log repository with aggregation queries"
```

---

## Task 3: Service — 采集 + 聚合

**Files:**
- Create: `backend/app/services/model_usage_service.py`
- Test: `backend/tests/test_model_usage_service.py`

- [ ] **Step 1: 创建 service**

```python
"""
模型使用量统计服务
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.model_usage_log import ModelUsageLogRepository

from .base import BaseService


class ModelUsageService(BaseService):
    """模型使用量统计服务"""

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.repo = ModelUsageLogRepository(db)

    async def log_usage(
        self,
        provider_name: str,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_time_ms: float = 0.0,
        ttft_ms: Optional[float] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        source: str = "chat",
        user_id: Optional[str] = None,
        model_type: str = "chat",
    ) -> None:
        """记录一次模型调用日志。失败只记 warning，不抛异常。"""
        try:
            await self.repo.create(
                {
                    "provider_name": provider_name,
                    "model_name": model_name,
                    "model_type": model_type,
                    "user_id": user_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_time_ms": total_time_ms,
                    "ttft_ms": ttft_ms,
                    "status": status,
                    "error_message": error_message,
                    "source": source,
                }
            )
            await self.commit()
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to log model usage: {e}")

    async def get_stats(
        self,
        period: str = "24h",
        granularity: str = "hour",
        provider_name: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取使用量统计"""
        period_map = {
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        delta = period_map.get(period, timedelta(hours=24))
        since = datetime.now(timezone.utc) - delta

        summary = await self.repo.get_summary(since, provider_name, model_name)
        timeline = await self.repo.get_timeline(since, granularity, provider_name, model_name)
        by_model = await self.repo.get_by_model(since, provider_name)

        return {
            "summary": summary,
            "timeline": timeline,
            "by_model": by_model,
        }

    async def cleanup(self, days: int = 90) -> int:
        """清理过期日志"""
        count = await self.repo.cleanup_old_logs(days)
        await self.commit()
        return count
```

- [ ] **Step 2: 写测试**

创建 `backend/tests/test_model_usage_service.py`：

```python
import pytest


class TestModelUsageService:
    @pytest.mark.asyncio
    async def test_log_usage_does_not_raise(self):
        """log_usage 失败不应抛异常"""
        from app.services.model_usage_service import ModelUsageService
        assert hasattr(ModelUsageService, 'log_usage')

    @pytest.mark.asyncio
    async def test_get_stats_returns_structure(self):
        """get_stats 应返回 summary + timeline + by_model"""
        from app.services.model_usage_service import ModelUsageService
        assert hasattr(ModelUsageService, 'get_stats')
```

- [ ] **Step 3: 运行测试**

Run: `cd backend && python -m pytest tests/test_model_usage_service.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/model_usage_service.py backend/tests/test_model_usage_service.py
git commit -m "feat: add model_usage_service with logging and aggregation"
```

---

## Task 4: API 端点

**Files:**
- Create: `backend/app/api/v1/model_usage.py`
- Test: `backend/tests/test_model_usage_api.py`

- [ ] **Step 1: 创建 API**

```python
"""
模型使用量统计 API
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.model_usage_service import ModelUsageService

router = APIRouter(prefix="/v1/models/usage", tags=["ModelUsage"])


@router.get("/stats")
async def get_usage_stats(
    period: str = Query(default="24h", description="时间范围：24h / 7d / 30d"),
    granularity: str = Query(default="hour", description="时间粒度：hour / day"),
    provider_name: Optional[str] = Query(default=None, description="按供应商过滤"),
    model_name: Optional[str] = Query(default=None, description="按模型过滤"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取模型使用量统计"""
    service = ModelUsageService(db)
    stats = await service.get_stats(
        period=period,
        granularity=granularity,
        provider_name=provider_name,
        model_name=model_name,
    )
    return success_response(data=stats, message="获取使用量统计成功")
```

- [ ] **Step 2: 注册路由**

在 FastAPI app 的路由注册处（通常在 `backend/app/main.py` 或 `backend/app/api/__init__.py`）加入：

```python
from app.api.v1.model_usage import router as model_usage_router
app.include_router(model_usage_router)
```

- [ ] **Step 3: 写测试**

创建 `backend/tests/test_model_usage_api.py`：

```python
import pytest
from httpx import AsyncClient


class TestModelUsageAPI:
    @pytest.mark.asyncio
    async def test_get_stats_empty(self, client: AsyncClient, auth_headers):
        """无数据时应返回空统计"""
        response = await client.get(
            "/api/v1/models/usage/stats?period=24h",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["summary"]["total_calls"] == 0
        assert data["timeline"] == []
        assert data["by_model"] == []

    @pytest.mark.asyncio
    async def test_get_stats_with_filters(self, client: AsyncClient, auth_headers):
        """带过滤参数应正常返回"""
        response = await client.get(
            "/api/v1/models/usage/stats?period=7d&granularity=day&provider_name=test",
            headers=auth_headers,
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_stats_requires_auth(self, client: AsyncClient):
        """无认证应返回 401"""
        response = await client.get("/api/v1/models/usage/stats")
        assert response.status_code == 401
```

- [ ] **Step 4: 运行测试**

Run: `cd backend && python -m pytest tests/test_model_usage_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/model_usage.py backend/tests/test_model_usage_api.py
git commit -m "feat: add model usage stats API endpoint"
```

---

## Task 5: 在 ModelService 中插入日志采集

**Files:**
- Modify: `backend/app/services/model_service.py`

- [ ] **Step 1: 在 test_output 和 test_output_stream 中插入采集**

在 `ModelService.__init__` 中加入：
```python
self.usage_service = ModelUsageService(db)
```

在 `test_output` 方法的 `model.ainvoke` 调用前后加入计时和日志：
```python
import time

start = time.monotonic()
try:
    response = await model.ainvoke(input_text)
    elapsed = (time.monotonic() - start) * 1000
    content = response.content if hasattr(response, "content") else str(response)
    await self.usage_service.log_usage(
        provider_name=provider_name,
        model_name=model_name,
        total_time_ms=elapsed,
        status="success",
        source="playground",
        user_id=user_id,
    )
    return str(content)
except Exception as e:
    elapsed = (time.monotonic() - start) * 1000
    await self.usage_service.log_usage(
        provider_name=provider_name,
        model_name=model_name,
        total_time_ms=elapsed,
        status="error",
        error_message=str(e),
        source="playground",
        user_id=user_id,
    )
    raise
```

在 `test_output_stream` 的 metrics 事件 yield 之前也加入日志采集（复用 metrics 数据）。

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/model_service.py
git commit -m "feat: integrate usage logging into model service"
```

---

## Task 6: 数据清理定时任务

**Files:**
- Modify: `backend/app/main.py`（或启动入口文件）

- [ ] **Step 1: 注册启动清理任务**

在 FastAPI app 的 `on_startup` 或 `lifespan` 中加入：

```python
import asyncio
from app.core.database import get_db_session
from app.services.model_usage_service import ModelUsageService

async def usage_log_cleanup_loop():
    """每 24 小时清理过期日志"""
    while True:
        try:
            async with get_db_session() as db:
                service = ModelUsageService(db)
                count = await service.cleanup(days=90)
                if count > 0:
                    from loguru import logger
                    logger.info(f"Cleaned up {count} old usage log entries")
        except Exception as e:
            from loguru import logger
            logger.warning(f"Usage log cleanup failed: {e}")
        await asyncio.sleep(86400)  # 24 hours
```

在 startup 中 `asyncio.create_task(usage_log_cleanup_loop())`。

- [ ] **Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: add periodic usage log cleanup task"
```

---

## Task 7: 前端 — 安装 recharts + 类型扩展

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/types/models.ts`
- Modify: `frontend/hooks/queries/models.ts`

- [ ] **Step 1: 安装 recharts**

Run: `cd frontend && npm install recharts`

- [ ] **Step 2: 新增统计类型**

在 `frontend/types/models.ts` 中新增：

```typescript
// ==================== Usage Stats ====================

export interface UsageStatsSummary {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  avg_response_time_ms: number
  error_rate: number
}

export interface UsageTimelinePoint {
  timestamp: string
  calls: number
  tokens: number
  avg_time_ms: number
}

export interface UsageByModel {
  model_name: string
  calls: number
  tokens: number
}

export interface ModelUsageStats {
  summary: UsageStatsSummary
  timeline: UsageTimelinePoint[]
  by_model: UsageByModel[]
}
```

- [ ] **Step 3: 新增 useModelUsageStats hook**

在 `frontend/hooks/queries/models.ts` 中新增：

```typescript
export function useModelUsageStats(params: {
  period?: string
  granularity?: string
  provider_name?: string
  model_name?: string
  enabled?: boolean
}) {
  const searchParams = new URLSearchParams()
  if (params.period) searchParams.set('period', params.period)
  if (params.granularity) searchParams.set('granularity', params.granularity)
  if (params.provider_name) searchParams.set('provider_name', params.provider_name)
  if (params.model_name) searchParams.set('model_name', params.model_name)

  return useQuery({
    queryKey: [...modelKeys.all, 'usage', params],
    queryFn: async (): Promise<ModelUsageStats> => {
      return await apiGet<ModelUsageStats>(`models/usage/stats?${searchParams.toString()}`)
    },
    enabled: params.enabled !== false,
    retry: false,
    staleTime: STALE_TIME.SHORT,
  })
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/types/models.ts frontend/hooks/queries/models.ts
git commit -m "feat: add recharts dependency and usage stats types/hooks"
```

---

## Task 8: 前端统计组件

**Files:**
- Create: `frontend/app/settings/models/components/detail-panel/stats-tab/summary-cards.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/stats-tab/usage-chart.tsx`
- Create: `frontend/app/settings/models/components/detail-panel/stats-tab/stats-tab.tsx`

- [ ] **Step 1: 创建 summary-cards.tsx**

Props: `summary: UsageStatsSummary | undefined`

横向排列 4 个摘要卡片：总调用次数、总 token 消耗（input + output）、平均响应时间、错误率。loading 时显示 skeleton。

- [ ] **Step 2: 创建 usage-chart.tsx**

Props:
- `timeline: UsageTimelinePoint[]`
- `byModel: UsageByModel[]`

上方：recharts `LineChart` 展示调用量 + token 消耗趋势（双 Y 轴）。
下方：简单表格展示按模型分组的调用排行。

空数据时显示空状态插图 + "暂无调用数据"。

- [ ] **Step 3: 创建 stats-tab.tsx**

统计 Tab 容器。Props: `selectedProvider: string | null`

顶部：时间范围选择器（24h / 7d / 30d 三个按钮），默认 24h。
使用 `useModelUsageStats` hook，传入 period + provider_name。
渲染 `SummaryCards` + `UsageChart`。

- [ ] **Step 4: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/stats-tab/
git commit -m "feat: create stats tab with summary cards and usage chart"
```

---

## Task 9: 集成统计 Tab 到 detail-panel

**Files:**
- Modify: `frontend/app/settings/models/components/detail-panel/detail-panel.tsx`

- [ ] **Step 1: 替换统计 Tab 占位**

将 detail-panel.tsx 中统计 Tab 的 "Coming Soon" 占位替换为 `<StatsTab selectedProvider={selectedProvider} />`。

- [ ] **Step 2: Commit**

```bash
git add frontend/app/settings/models/components/detail-panel/detail-panel.tsx
git commit -m "feat: integrate stats tab into detail panel"
```

---

## Task 10: 前端测试

**Files:**
- Create: `frontend/app/settings/models/__tests__/stats-tab.test.tsx`

- [ ] **Step 1: 写测试**

测试：
- 空数据时显示空状态
- 摘要卡片正确映射数据
- 时间范围切换触发重新查询
- 按 Provider 过滤

Mock `useModelUsageStats` 返回不同数据。

- [ ] **Step 2: 运行测试**

Run: `cd frontend && npx vitest run app/settings/models/__tests__/stats-tab.test.tsx --reporter=verbose`

- [ ] **Step 3: Commit**

```bash
git add frontend/app/settings/models/__tests__/stats-tab.test.tsx
git commit -m "test: add stats tab tests"
```

---

## Task 11: 集成验证

- [ ] **Step 1: 运行后端全量测试**

Run: `cd backend && python -m pytest tests/ -v --tb=short`

- [ ] **Step 2: 运行前端构建**

Run: `cd frontend && npx next build`

- [ ] **Step 3: 修复问题（如有）并 Commit**
