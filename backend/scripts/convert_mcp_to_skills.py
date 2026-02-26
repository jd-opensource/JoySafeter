#!/usr/bin/env python3
"""
MCP 工具 → Skills 转换器（带分类优化）
用法: python scripts/convert_mcp_to_skills.py
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml

# 分类优化映射
CATEGORY_OPTIMIZATION = {
    # === 合并单工具类别 ===
    "sqli": "web_security",
    "parameter_discovery": "web_security",
    "penetration_testing": "attack",
    "cryptographic_vulnerability": "attack",
    "data_security": "forensics",
    # === 修正命名 ===
    "bugbounty": "bug_bounty",
    # === 移动错位工具 ===
    "wpscan_analyze": "web_security",
    "burpsuite_alternative_scan": "web_security",
    "anew_data_processing": "data_processing",
    "dirsearch_scan": "web_security",
    "feroxbuster_scan": "web_security",
    "wafw00f_scan": "web_security",
    "dotdotpwn_scan": "web_security",
    "dirb_scan": "web_security",
    "gobuster_scan": "web_security",
    "ffuf_scan": "web_security",
    "amass_scan": "subdomain_discovery",
    "subfinder_scan": "subdomain_discovery",
    "fierce_scan": "subdomain_discovery",
    "uro_url_filtering": "data_processing",
    "qsreplace_parameter_replacement": "data_processing",
    "x8_parameter_discovery": "parameter_discovery",
}


def get_optimized_category(category: str, tool_name: str) -> str:
    """获取优化后的类别"""
    key = f"{category}-{tool_name}"
    if key in CATEGORY_OPTIMIZATION:
        return CATEGORY_OPTIMIZATION[key]
    if category in CATEGORY_OPTIMIZATION:
        return CATEGORY_OPTIMIZATION[category]
    return category


def load_yaml_config(yaml_path: Path) -> dict:
    """加载 YAML 配置"""
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_file_content(file_path: Path) -> str:
    """读取文件内容"""
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def generate_manifest_md(config: dict, category: str) -> str:
    """生成符合前端格式的 manifest.md"""

    tool_name = config.get("name", "unknown")
    tags = config.get("tags", [])

    # 从 parameters 推断 capabilities
    parameters = config.get("parameters", [])
    capabilities = []
    for param in parameters:
        param_name = param.get("name", "")
        capabilities.append(param_name.replace("_", "-"))

    # 如果没有参数，从 tags 推断
    if not capabilities and tags:
        capabilities = tags[:3]

    # 构建 YAML 前置数据
    yaml_front = f"""---
name: {tool_name}
capabilities: {capabilities}
category: {category}
tags: {tags}
---

# {tool_name.replace("_", " ").title()}

{config.get("description", "No description available.")}

## Parameters
"""

    # 添加参数说明
    if parameters:
        for param in parameters:
            required = "Required" if param.get("required") else "Optional"
            default = f" (default: {param.get('default', '')})" if param.get("default") else ""
            yaml_front += f"- **{param.get('name')}** ({param.get('type')}, {required}){default}: {param.get('description', '')}\n"
    else:
        yaml_front += "\nNo parameters required.\n"

    # 添加使用说明
    yaml_front += f"""

## Usage

This tool is part of the {category} category.

**Endpoint:** `{config.get("endpoint", "N/A")}`

**Returns:** {config.get("returns", "Execution results")}

## Files Included

- `{tool_name}.yaml` - Tool configuration
- `{tool_name}.py` - Python implementation

---

*Converted from MCP tool - Source: backend/mcp_handlers/*
"""

    return yaml_front


def convert_mcp_tool_to_skill(yaml_path: Path, handlers_dir: Path, optimize_category: bool = True) -> Optional[dict]:
    """转换单个 MCP 工具为 Skill（修正版：生成 manifest.md）"""

    try:
        # 1. 加载 YAML 配置
        config = load_yaml_config(yaml_path)

        # 2. 基本信息
        tool_name = config.get("name", yaml_path.stem)
        original_category = config.get("category", "general")

        # 3. 应用分类优化
        if optimize_category:
            category = get_optimized_category(original_category, tool_name)
        else:
            category = original_category

        # 4. 生成 manifest.md（前端主清单）
        manifest_content = generate_manifest_md(config, category)

        # 5. 构建文件列表（manifest.md 在第一位）
        files = []
        base_name = yaml_path.stem

        # manifest.md（新生成，放第一位）
        files.append({"name": "manifest.md", "content": manifest_content, "language": "markdown"})

        # YAML 文件（保留原始配置）
        yaml_content = read_file_content(yaml_path)
        files.append({"name": f"{base_name}.yaml", "content": yaml_content, "language": "yaml"})

        # Python 文件（如果存在）
        py_path = yaml_path.parent / f"{base_name}.py"
        if py_path.exists():
            py_content = read_file_content(py_path)
            files.append({"name": f"{base_name}.py", "content": py_content, "language": "python"})

        # Markdown 文件（如果存在）
        md_path = yaml_path.parent / f"{base_name}.md"
        md_content = read_file_content(md_path)
        if md_content:
            files.append({"name": f"{base_name}.md", "content": md_content, "language": "markdown"})

        # 6. 构建 Skill
        skill = {
            "id": f"{category}-{tool_name}",
            "name": tool_name.replace("_", " ").title(),
            "description": config.get("description", ""),
            "license": config.get("license", "MIT"),
            "content": manifest_content,  # manifest.md 内容
            "files": files,
            "source": "mcp",
            "updatedAt": int(datetime.now().timestamp() * 1000),
        }

        return skill

    except Exception as e:
        print(f"  ✗ 转换失败: {yaml_path.name} - {e}")
        return None


def scan_and_convert(
    handlers_dir: Path,
    output_file: Path,
    categories: Optional[List[str]] = None,
    max_tools: Optional[int] = None,
    optimize_category: bool = True,
    show_category_report: bool = True,
) -> dict:
    """扫描并转换 MCP 工具"""

    skills = []
    total_scanned = 0
    category_changes = {}

    # 核心类别
    CORE_CATEGORIES = [
        "web_security",
        "network_scanning",
        "binary_analysis",
        "container_security",
        "vulnerability_scanning",
        "authentication_testing",
    ]

    target_categories = categories or CORE_CATEGORIES

    print("=" * 60)
    print("MCP 工具 → Skills 转换器")
    print("=" * 60)
    print(f"目标类别: {', '.join(target_categories)}")
    print(f"分类优化: {'启用' if optimize_category else '禁用'}")
    if max_tools:
        print(f"最大工具数: {max_tools}")
    print("-" * 60)

    # 遍历目录
    for category_dir in handlers_dir.iterdir():
        if not category_dir.is_dir():
            continue

        category = category_dir.name

        # 跳过特殊目录
        if category in ["attack_strategy", "strategy", "scenarios", "knowledge"]:
            continue

        # 过滤类别
        if category not in target_categories:
            continue

        print(f"\n扫描类别: {category}")

        # 查找所有 YAML 文件
        yaml_files = list(category_dir.glob("*.yaml"))
        for yaml_path in yaml_files:
            # 检查数量限制
            if max_tools and len(skills) >= max_tools:
                print(f"\n已达到最大工具数限制: {max_tools}")
                break

            total_scanned += 1
            skill = convert_mcp_tool_to_skill(yaml_path, handlers_dir, optimize_category)
            if skill:
                skills.append(skill)

                # 记录分类变化
                tool_name = yaml_path.stem
                original_cat = category
                optimized_cat = skill["id"].split("-")[0]

                if optimize_category and original_cat != optimized_cat:
                    if original_cat not in category_changes:
                        category_changes[original_cat] = {}
                    if optimized_cat not in category_changes[original_cat]:
                        category_changes[original_cat][optimized_cat] = []
                    category_changes[original_cat][optimized_cat].append(tool_name)

                print(
                    f"  ✓ {skill['id']}{' ← ' + original_cat if optimize_category and original_cat != optimized_cat else ''}"
                )

        if max_tools and len(skills) >= max_tools:
            break

    # 输出结果
    result = {
        "skills": skills,
        "total": len(skills),
        "scanned": total_scanned,
        "categories": list(set(s["id"].split("-")[0] for s in skills)),
        "generated_at": datetime.now().isoformat(),
    }

    # 保存到文件
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("转换完成!")
    print(f"  扫描: {total_scanned} 个工具")
    print(f"  转换: {len(skills)} 个技能")
    print(f"  类别: {len(result['categories'])} 个")
    print(f"  输出: {output_file}")
    print("=" * 60)

    # 显示分类优化报告
    if show_category_report and optimize_category and category_changes:
        print("\n" + "=" * 60)
        print("分类优化报告")
        print("=" * 60)
        for original, targets in category_changes.items():
            for optimized, tools in targets.items():
                print(f"\n{original} → {optimized}:")
                for tool in tools:
                    print(f"  - {tool}")
        print("=" * 60)

    return result


if __name__ == "__main__":
    import sys

    # 配置路径
    backend_dir = Path(__file__).parent.parent
    handlers_dir = backend_dir / "mcp_handlers"
    output_file = backend_dir / "scripts" / "converted_skills.json"

    if not handlers_dir.exists():
        print(f"错误: 处理器目录不存在: {handlers_dir}")
        print("提示: dynamic_engine 已移除，请提供新的 MCP handlers 目录后再执行转换。")
        sys.exit(1)

    # 解析命令行参数
    categories = None
    max_tools = None
    optimize_category = True
    show_report = True

    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith("--categories="):
                categories = arg.split("=")[1].split(",")
            elif arg.startswith("--max="):
                max_tools = int(arg.split("=")[1])
            elif arg == "--all":
                categories = None
                max_tools = None
            elif arg == "--no-optimize":
                optimize_category = False
            elif arg == "--no-report":
                show_report = False
            elif arg == "--help":
                print("用法: python convert_mcp_to_skills.py [选项]")
                print("\n选项:")
                print("  --categories=CATS    指定类别（逗号分隔）")
                print("  --max=N              最大转换工具数")
                print("  --all                 转换全部工具")
                print("  --no-optimize        禁用分类优化")
                print("  --no-report          不显示分类优化报告")
                print("\n示例:")
                print("  python convert_mcp_to_skills.py                    # 转换核心类别")
                print("  python convert_mcp_to_skills.py --max=20             # 只转20个")
                print("  python convert_mcp_to_skills.py --all --no-optimize  # 全部不优化")
                sys.exit(0)

    # 执行转换
    scan_and_convert(handlers_dir, output_file, categories, max_tools, optimize_category, show_report)
