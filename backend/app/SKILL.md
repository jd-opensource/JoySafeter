# SKILL 后端功能说明文档

## 概述

SKILL（技能）模块是平台的核心功能之一，用于管理和组织可复用的技能资源。每个技能可以包含描述、内容、标签、文件等丰富的信息，支持公开分享和私有管理。

## 架构设计

### 分层架构

SKILL 模块采用经典的分层架构设计：

```
API Layer (api/v1/skills.py)
    ↓
Service Layer (services/skill_service.py)
    ↓
Repository Layer (repositories/skill.py)
    ↓
Model Layer (models/skill.py)
```

### 核心组件

1. **模型层 (Models)**
   - `Skill`: 技能主表模型
   - `SkillFile`: 技能文件关联表模型

2. **仓库层 (Repositories)**
   - `SkillRepository`: 技能数据访问层
   - `SkillFileRepository`: 技能文件数据访问层

3. **服务层 (Services)**
   - `SkillService`: 技能业务逻辑和权限校验

4. **API层 (API)**
   - RESTful API 端点，提供完整的 CRUD 操作

## 数据模型

### Skill 模型

技能主表，存储技能的核心信息：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键，自动生成 |
| `name` | String(255) | 技能名称，必填 |
| `description` | Text | 技能描述，必填 |
| `content` | Text | 技能内容，必填 |
| `tags` | JSONB | 标签列表，默认为空列表 |
| `source_type` | String(50) | 来源类型，默认为 "local" |
| `source_url` | String(1024) | 来源 URL，可选 |
| `root_path` | String(512) | 根路径，可选 |
| `owner_id` | String(255) | 拥有者 ID，外键关联 user.id |
| `created_by_id` | String(255) | 创建者 ID，外键关联 user.id，必填 |
| `is_public` | Boolean | 是否公开，默认为 False |
| `license` | String(100) | 许可证信息，可选 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

**约束和索引：**
- 唯一约束：`(owner_id, name)` - 同一拥有者的技能名称必须唯一
- 索引：
  - `skills_owner_idx`: 拥有者索引
  - `skills_created_by_idx`: 创建者索引
  - `skills_public_idx`: 公开状态索引
  - `skills_tags_idx`: 标签 GIN 索引（支持 JSONB 查询）

### SkillFile 模型

技能文件关联表，存储技能关联的文件信息：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键，自动生成 |
| `skill_id` | UUID | 技能 ID，外键关联 skills.id |
| `path` | String(512) | 文件路径，必填 |
| `file_name` | String(255) | 文件名，必填 |
| `file_type` | String(50) | 文件类型，必填 |
| `content` | Text | 文件内容，可选 |
| `storage_type` | String(20) | 存储类型，默认为 "database" |
| `storage_key` | String(512) | 存储键（如对象存储的 key），可选 |
| `size` | Integer | 文件大小（字节），默认为 0 |
| `created_at` | DateTime | 创建时间 |
| `updated_at` | DateTime | 更新时间 |

**索引：**
- `skill_files_skill_idx`: 技能 ID 索引
- `skill_files_path_idx`: 技能 ID + 路径复合索引

## 核心功能

### 1. 技能列表查询

**功能描述：** 获取技能列表，支持按用户、公开状态、标签过滤。

**权限控制：**
- 未登录用户：只能查看公开技能
- 已登录用户：可查看自己的技能 + 公开技能

**查询参数：**
- `include_public` (bool): 是否包含公开技能，默认 True
- `tags` (List[str]): 标签过滤，支持多标签筛选

**实现位置：**
- API: `GET /v1/skills`
- Service: `SkillService.list_skills()`
- Repository: `SkillRepository.list_by_user()`

**查询逻辑：**
1. 如果 `user_id` 存在且 `include_public=True`：返回 `owner_id == user_id` 或 `is_public == True` 或 `owner_id == None`（系统级公共技能）
2. 如果 `user_id` 存在且 `include_public=False`：只返回 `owner_id == user_id` 的技能
3. 如果 `user_id` 不存在且 `include_public=True`：返回所有公开技能
4. 如果 `user_id` 不存在且 `include_public=False`：不返回任何结果
5. 如果指定了 `tags`，使用 JSONB 的 `contains` 操作符进行标签过滤

### 2. 技能详情查询

**功能描述：** 根据技能 ID 获取技能详情，包含关联的文件列表。

**权限控制：**
- 拥有者：可以访问自己的技能
- 其他用户：只能访问公开的技能
- 未登录用户：只能访问公开的技能

**实现位置：**
- API: `GET /v1/skills/{skill_id}`
- Service: `SkillService.get_skill()`
- Repository: `SkillRepository.get_with_files()`

**权限检查逻辑：**
```python
if skill.owner_id and skill.owner_id != current_user_id and not skill.is_public:
    raise ForbiddenException("You don't have permission to access this skill")
```

### 3. 创建技能

**功能描述：** 创建新的技能，支持同时创建关联的文件。

**权限要求：** 需要登录

**实现位置：**
- API: `POST /v1/skills`
- Service: `SkillService.create_skill()`

**业务规则：**
1. 如果未指定 `owner_id`，则使用 `created_by_id` 作为拥有者
2. 检查同一拥有者下是否存在同名技能，如果存在则抛出异常
3. 支持在创建时同时添加文件列表
4. 文件通过 `files` 参数传入，每个文件包含：
   - `path`: 文件路径
   - `file_name`: 文件名
   - `file_type`: 文件类型
   - `content`: 文件内容（可选）
   - `storage_type`: 存储类型（默认 "database"）
   - `storage_key`: 存储键（可选）
   - `size`: 文件大小（默认 0）

**请求体示例：**
```json
{
  "name": "Python 数据分析",
  "description": "使用 Python 进行数据分析的技能",
  "content": "详细的技能内容...",
  "tags": ["python", "data-analysis"],
  "source_type": "local",
  "is_public": false,
  "files": [
    {
      "path": "/examples",
      "file_name": "example.py",
      "file_type": "python",
      "content": "print('Hello World')",
      "storage_type": "database",
      "size": 20
    }
  ]
}
```

### 4. 更新技能

**功能描述：** 更新已存在的技能信息。

**权限要求：** 只有拥有者可以更新自己的技能

**实现位置：**
- API: `PUT /v1/skills/{skill_id}`
- Service: `SkillService.update_skill()`

**业务规则：**
1. 权限检查：只有拥有者可以更新
2. 如果更新名称，需要检查新名称在同一拥有者下是否已存在
3. 支持部分更新，所有字段都是可选的
4. 更新后自动刷新技能信息

**可更新字段：**
- `name`: 技能名称
- `description`: 技能描述
- `content`: 技能内容
- `tags`: 标签列表
- `source_type`: 来源类型
- `source_url`: 来源 URL
- `root_path`: 根路径
- `owner_id`: 拥有者 ID
- `is_public`: 是否公开
- `license`: 许可证

### 5. 删除技能

**功能描述：** 删除技能及其关联的所有文件。

**权限要求：** 只有拥有者可以删除自己的技能

**实现位置：**
- API: `DELETE /v1/skills/{skill_id}`
- Service: `SkillService.delete_skill()`

**业务规则：**
1. 权限检查：只有拥有者可以删除
2. 级联删除：删除技能时自动删除所有关联的文件（通过外键约束）
3. 使用 `SkillFileRepository.delete_by_skill()` 显式删除文件记录

### 6. 添加文件

**功能描述：** 向已存在的技能添加文件。

**权限要求：** 只有拥有者可以向自己的技能添加文件

**实现位置：**
- API: `POST /v1/skills/{skill_id}/files`
- Service: `SkillService.add_file()`

**业务规则：**
1. 权限检查：只有拥有者可以添加文件
2. 文件信息包括路径、文件名、类型、内容等
3. 支持多种存储类型（默认 "database"）

### 7. 删除文件

**功能描述：** 删除技能关联的特定文件。

**权限要求：** 只有拥有者可以删除自己技能的文件

**实现位置：**
- API: `DELETE /v1/skills/files/{file_id}`
- Service: `SkillService.delete_file()`

**业务规则：**
1. 权限检查：通过文件的 `skill_id` 找到对应的技能，检查拥有者权限
2. 删除指定的文件记录

## 权限控制

### 访问权限

| 操作 | 拥有者 | 其他用户 | 未登录用户 |
|------|--------|----------|------------|
| 查看自己的技能 | ✅ | ❌ | ❌ |
| 查看公开技能 | ✅ | ✅ | ✅ |
| 创建技能 | ✅ | ❌ | ❌ |
| 更新自己的技能 | ✅ | ❌ | ❌ |
| 删除自己的技能 | ✅ | ❌ | ❌ |
| 添加文件 | ✅ | ❌ | ❌ |
| 删除文件 | ✅ | ❌ | ❌ |

### 权限检查实现

所有权限检查都在 `SkillService` 层实现：

1. **查看权限：** 在 `get_skill()` 方法中检查
2. **更新权限：** 在 `update_skill()` 方法中检查
3. **删除权限：** 在 `delete_skill()` 方法中检查
4. **文件操作权限：** 在 `add_file()` 和 `delete_file()` 方法中检查

## 数据访问层

### SkillRepository

提供技能数据访问方法：

- `list_by_user()`: 根据用户 ID、公开状态、标签查询技能列表
- `get_with_files()`: 获取技能及其关联的文件（使用 `selectinload` 预加载）
- `count_by_user()`: 统计用户拥有的技能数量
- `get_by_name_and_owner()`: 根据名称和拥有者查询技能（用于唯一性检查）

### SkillFileRepository

提供技能文件数据访问方法：

- `list_by_skill()`: 获取技能的所有文件
- `delete_by_skill()`: 删除技能的所有文件（批量删除）

## API 端点

### 基础路径

所有技能相关的 API 端点都在 `/v1/skills` 路径下。

### 端点列表

| 方法 | 路径 | 说明 | 需要认证 |
|------|------|------|----------|
| GET | `/v1/skills` | 获取技能列表 | 可选 |
| POST | `/v1/skills` | 创建技能 | ✅ |
| GET | `/v1/skills/{skill_id}` | 获取技能详情 | 可选 |
| PUT | `/v1/skills/{skill_id}` | 更新技能 | ✅ |
| DELETE | `/v1/skills/{skill_id}` | 删除技能 | ✅ |
| POST | `/v1/skills/{skill_id}/files` | 添加文件 | ✅ |
| DELETE | `/v1/skills/files/{file_id}` | 删除文件 | ✅ |

### 响应格式

所有 API 响应都遵循统一的格式：

**成功响应：**
```json
{
  "success": true,
  "data": { ... }
}
```

**错误响应：**
```json
{
  "success": false,
  "error": "错误信息"
}
```

## 异常处理

技能模块使用以下自定义异常：

- `NotFoundException`: 资源不存在（如技能或文件不存在）
- `ForbiddenException`: 权限不足（如非拥有者尝试修改技能）
- `BadRequestException`: 请求参数错误（如同名技能已存在）

所有异常都在 `SkillService` 层抛出，由 API 层的全局异常处理器统一处理。

## 数据库关系

### 外键关系

1. **Skill → AuthUser (owner)**
   - `owner_id` → `user.id`
   - `ondelete="SET NULL"`: 用户删除时，拥有者设为 NULL

2. **Skill → AuthUser (created_by)**
   - `created_by_id` → `user.id`
   - `ondelete="CASCADE"`: 用户删除时，删除其创建的所有技能

3. **SkillFile → Skill**
   - `skill_id` → `skills.id`
   - `ondelete="CASCADE"`: 技能删除时，级联删除所有关联文件

### 关系加载策略

- `Skill.owner`: `lazy="selectin"` - 使用 selectin 加载
- `Skill.created_by`: `lazy="selectin"` - 使用 selectin 加载
- `Skill.files`: `lazy="selectin"` - 使用 selectin 加载，支持级联删除
- `SkillFile.skill`: `lazy="selectin"` - 使用 selectin 加载

## 使用示例

### 创建技能

```python
from app.services.skill_service import SkillService

service = SkillService(db)
skill = await service.create_skill(
    created_by_id="user123",
    name="Python 爬虫",
    description="使用 Python 进行网页爬取的技能",
    content="详细的技能内容...",
    tags=["python", "web-scraping"],
    is_public=True,
    files=[
        {
            "path": "/examples",
            "file_name": "scraper.py",
            "file_type": "python",
            "content": "import requests\n...",
            "storage_type": "database",
            "size": 1024
        }
    ]
)
```

### 查询技能列表

```python
# 获取当前用户的所有技能（包括公开的）
skills = await service.list_skills(
    current_user_id="user123",
    include_public=True,
    tags=["python"]
)
```

### 更新技能

```python
skill = await service.update_skill(
    skill_id=skill.id,
    current_user_id="user123",
    description="更新后的描述",
    is_public=False
)
```

## 扩展性考虑

### 未来可能的扩展

1. **版本管理：** 支持技能版本控制，记录历史版本
2. **评分系统：** 允许用户对公开技能进行评分和评论
3. **使用统计：** 记录技能的使用次数和频率
4. **导入导出：** 支持技能的批量导入和导出
5. **模板系统：** 支持从模板创建技能
6. **协作功能：** 支持多人协作编辑技能
7. **搜索优化：** 使用全文搜索提升搜索性能
8. **文件存储优化：** 支持大文件使用对象存储（S3、OSS 等）

## 注意事项

1. **唯一性约束：** 同一拥有者的技能名称必须唯一，创建和更新时都会检查
2. **权限边界：** 所有权限检查都在服务层实现，确保数据安全
3. **级联删除：** 删除技能时会自动删除所有关联文件，注意数据备份
4. **标签查询：** 使用 PostgreSQL 的 JSONB GIN 索引，支持高效的标签查询
5. **关系加载：** 使用 `selectinload` 策略，避免 N+1 查询问题
6. **事务管理：** 所有写操作都在事务中执行，确保数据一致性

## 相关文件

- 模型定义：`app/models/skill.py`
- 数据访问：`app/repositories/skill.py`
- 业务逻辑：`app/services/skill_service.py`
- API 端点：`app/api/v1/skills.py`
- 数据库迁移：`alembic/versions/`
