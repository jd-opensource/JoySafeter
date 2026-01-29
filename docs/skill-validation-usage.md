# Skill 验证使用说明

本文档说明如何在前后端使用 Skill 验证功能，确保符合 Agent Skills 规范。

## 后端验证

### 1. 数据库迁移

已创建迁移文件：`backend/alembic/versions/20260108_000002_000000000002_update_skills_agent_skills_spec.py`

**运行迁移**：
```bash
cd backend
alembic upgrade head
```

**迁移内容**：
- 将 `name` 字段从 `String(255)` 改为 `String(64)`
- 将 `description` 字段从 `Text` 改为 `String(1024)`
- 添加 `compatibility` 字段（`String(500)`, nullable）
- 添加 `metadata` 字段（`JSONB`, default={}）
- 添加 `allowed_tools` 字段（`JSONB`, default=[]）
- 自动截断超长数据（保留现有数据）

### 2. 验证器使用

**位置**：`backend/app/core/skill/validators.py`

**验证函数**：
```python
from app.core.skill.validators import (
    validate_skill_name,
    validate_skill_description,
    validate_compatibility,
    truncate_description,
    truncate_compatibility,
)

# 验证技能名称
is_valid, error = validate_skill_name(name, directory_name=None)
if not is_valid:
    raise BadRequestException(f"Invalid skill name: {error}")

# 验证描述
is_valid, error = validate_skill_description(description)
if not is_valid:
    description = truncate_description(description)  # 自动截断

# 验证兼容性（可选）
if compatibility:
    is_valid, error = validate_compatibility(compatibility)
    if not is_valid:
        compatibility = truncate_compatibility(compatibility)
```

**验证规则**：
- **name**: 最大 64 字符，小写字母数字和连字符（`^[a-z0-9]+(-[a-z0-9]+)*$`）
- **description**: 最大 1024 字符
- **compatibility**: 最大 500 字符（可选）

### 3. Service 层自动验证

`SkillService.create_skill()` 和 `SkillService.update_skill()` 已自动应用验证：

```python
# 创建技能时自动验证
skill = await skill_service.create_skill(
    created_by_id="user-123",
    name="web-research",  # 自动验证格式
    description="Research skills",  # 自动验证长度
    content="...",
    compatibility="Python 3.8+",  # 可选，自动验证长度
    metadata={"version": "1.0"},  # 可选
    allowed_tools=["search", "read"],  # 可选
)
```

### 4. API Schema 验证

**位置**：`backend/app/schemas/skill.py`

Pydantic schema 已更新：
- `SkillCreate.name`: `max_length=64`
- `SkillCreate.description`: `max_length=1024`
- `SkillCreate.compatibility`: `max_length=500` (可选)
- 新增字段：`metadata`, `allowed_tools`

## 前端验证

### 1. 验证器使用

**位置**：`frontend/utils/skillValidators.ts`

**导入验证函数**：
```typescript
import {
  validateSkillName,
  validateSkillDescription,
  validateCompatibility,
  normalizeSkillName,
  MAX_SKILL_NAME_LENGTH,
  MAX_SKILL_DESCRIPTION_LENGTH,
} from '@/utils/skillValidators';
```

**在表单中使用**：
```typescript
// 验证技能名称
const nameValidation = validateSkillName(formData.name);
if (!nameValidation.valid) {
  toast({
    variant: 'destructive',
    title: 'Invalid skill name',
    description: nameValidation.error,
  });
  return;
}

// 验证描述
const descValidation = validateSkillDescription(formData.description);
if (!descValidation.valid) {
  toast({
    variant: 'destructive',
    title: 'Invalid skill description',
    description: descValidation.error,
  });
  return;
}

// 规范化技能名称（帮助用户创建有效名称）
const normalizedName = normalizeSkillName(userInput);
```

### 2. 在 SkillsManager 中使用

**位置**：`frontend/app/skills/SkillsManager.tsx`

验证已在 `handleSave()` 中集成：

```typescript
const handleSave = async () => {
  // 基本检查
  if (!formData.name?.trim()) {
    toast({ variant: 'destructive', title: t('skills.nameRequired') });
    return;
  }

  // 验证技能名称
  const { validateSkillName, validateSkillDescription } = await import('@/utils/skillValidators');
  const nameValidation = validateSkillName(formData.name);
  if (!nameValidation.valid) {
    toast({
      variant: 'destructive',
      title: 'Invalid skill name',
      description: nameValidation.error,
    });
    return;
  }

  // 验证描述
  if (formData.description) {
    const descValidation = validateSkillDescription(formData.description);
    if (!descValidation.valid) {
      toast({
        variant: 'destructive',
        title: 'Invalid skill description',
        description: descValidation.error,
      });
      return;
    }
  }

  // 继续保存逻辑...
};
```

### 3. 类型定义

**位置**：`frontend/types.ts`

已更新 `Skill` 和 `SkillFrontmatter` 接口：

```typescript
export interface Skill {
  // ... 现有字段
  compatibility?: string | null;  // Max 500 characters
  metadata?: Record<string, string>;  // dict[str, str]
  allowed_tools?: string[];  // list[str]
}

export interface SkillFrontmatter {
  name: string;
  description: string;
  // ... 现有字段
  compatibility?: string;  // Max 500 characters
  metadata?: Record<string, string>;  // dict[str, str]
  'allowed-tools'?: string;  // Space-delimited string (per spec)
  allowed_tools?: string[];  // Also support array format
}
```

### 4. 实时验证示例

可以在输入框中添加实时验证：

```typescript
import { validateSkillName, normalizeSkillName } from '@/utils/skillValidators';

const [nameError, setNameError] = useState<string | null>(null);

const handleNameChange = (value: string) => {
  const validation = validateSkillName(value);
  if (!validation.valid) {
    setNameError(validation.error || null);
  } else {
    setNameError(null);
  }
  setFormData(prev => ({ ...prev, name: value }));
};

// 在输入框中使用
<Input
  value={formData.name}
  onChange={(e) => handleNameChange(e.target.value)}
  placeholder="web-research"
  maxLength={MAX_SKILL_NAME_LENGTH}
/>
{nameError && (
  <p className="text-sm text-red-500">{nameError}</p>
)}
```

## 验证规则总结

### Skill Name
- **最大长度**: 64 字符
- **格式**: 小写字母数字和连字符（`^[a-z0-9]+(-[a-z0-9]+)*$`）
- **示例**: `web-research`, `data-analysis`, `pdf-parser`
- **无效示例**: `Web Research` (大写), `web__research` (双下划线), `-web-research` (开头连字符)

### Description
- **最大长度**: 1024 字符
- **必需**: 是
- **自动截断**: 如果超长，后端会自动截断（警告但不拒绝）

### Compatibility
- **最大长度**: 500 字符
- **必需**: 否
- **用途**: 环境要求说明（如 "Python 3.8+", "Node.js 18+"）

### Metadata
- **类型**: `dict[str, str]`
- **必需**: 否
- **默认**: `{}`
- **用途**: 任意键值对元数据

### Allowed Tools
- **类型**: `list[str]`
- **必需**: 否
- **默认**: `[]`
- **用途**: 预批准的工具列表（实验性功能）

## 迁移检查清单

- [x] 创建数据库迁移文件
- [x] 更新 Skill 模型
- [x] 更新 SkillService 验证逻辑
- [x] 更新 API Schema
- [x] 创建前端验证器
- [x] 更新前端类型定义
- [x] 在 SkillsManager 中集成验证
- [ ] 运行数据库迁移（需要手动执行）
- [ ] 测试前端验证
- [ ] 测试后端验证

## 注意事项

1. **向后兼容**: 现有技能数据会自动截断，不会丢失
2. **自动截断**: 超长内容会自动截断（警告但不拒绝）
3. **目录名匹配**: 如果提供 `directory_name`，name 必须匹配（用于文件系统场景）
4. **前端验证**: 前端验证是用户体验优化，后端验证是最终保障

## 相关文件

- 后端验证器: `backend/app/core/skill/validators.py`
- 后端 Service: `backend/app/services/skill_service.py`
- 后端 Schema: `backend/app/schemas/skill.py`
- 数据库迁移: `backend/alembic/versions/20260108_000002_000000000002_update_skills_agent_skills_spec.py`
- 前端验证器: `frontend/utils/skillValidators.ts`
- 前端类型: `frontend/types.ts`
- 前端组件: `frontend/app/skills/SkillsManager.tsx`
