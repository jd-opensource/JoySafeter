"""上下文增强中间件 - 增强对话上下文和提示词质量"""

import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from langchain.agents.middleware.types import AgentState

if TYPE_CHECKING:
    pass

from deepagents.backends.protocol import BackendProtocol
from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from typing_extensions import NotRequired


class ContextEnhancementState(AgentState):
    """上下文增强中间件的状态"""

    enhanced_context: NotRequired[Dict[str, Any]]
    """增强的上下文信息"""

    project_info: NotRequired[Dict[str, Any]]
    """项目信息"""

    user_preferences: NotRequired[Dict[str, Any]]
    """用户偏好"""

    conversation_context: NotRequired[Dict[str, Any]]
    """对话上下文"""


class ContextEnhancementMiddleware(AgentMiddleware):
    """上下文增强中间件

    为AI模型提供丰富的上下文信息，包括：
    - 项目结构和文件分析
    - 用户偏好和历史模式
    - 对话上下文增强
    - 代码质量和最佳实践提示
    """

    state_schema = ContextEnhancementState

    def __init__(
        self,
        *,
        backend: BackendProtocol,
        context_path: str = "/context/",
        enable_project_analysis: bool = True,
        enable_user_preferences: bool = True,
        enable_conversation_enhancement: bool = True,
        max_context_length: int = 4000,
    ) -> None:
        """初始化上下文增强中间件"""
        self.backend = backend
        self.context_path = context_path.rstrip("/") + "/"
        self.enable_project_analysis = enable_project_analysis
        self.enable_user_preferences = enable_user_preferences
        self.enable_conversation_enhancement = enable_conversation_enhancement
        self.max_context_length = max_context_length

    def _analyze_project_structure(self, workspace_path: str) -> Dict[str, Any]:
        """分析项目结构"""
        if not self.enable_project_analysis:
            return {}

        try:
            path = Path(workspace_path)
            if not path.exists():
                return {}

            project_info = {
                "name": path.name,
                "path": str(path),
                "type": self._detect_project_type(path),
                "languages": self._detect_programming_languages(path),
                "frameworks": self._detect_frameworks(path),
                "key_files": self._get_key_files(path),
                "recent_files": self._get_recent_files(path),
                "project_stats": self._get_project_stats(path),
            }

            return project_info
        except Exception as e:
            print(f"Warning: Project analysis failed: {e}")
            return {}

    def _detect_project_type(self, path: Path) -> str:
        """检测项目类型"""
        indicators = {
            "web": ["package.json", "requirements.txt", "composer.json", "Gemfile"],
            "mobile": ["Podfile", "build.gradle", "Info.plist", "AndroidManifest.xml"],
            "desktop": ["CMakeLists.txt", "Cargo.toml", "setup.py", "pom.xml"],
            "data_science": ["requirements.txt", "environment.yml", "Dockerfile"],
            "game": ["main.js", "index.html", "manifest.xml"],
        }

        files = [f.name for f in path.iterdir() if f.is_file()]

        for project_type, indicator_files in indicators.items():
            if any(indicator in files for indicator in indicator_files):
                return project_type

        return "general"

    def _detect_programming_languages(self, path: Path) -> List[str]:
        """检测使用的编程语言"""
        language_extensions = {
            "Python": [".py"],
            "JavaScript": [".js", ".mjs", ".cjs"],
            "TypeScript": [".ts"],
            "Java": [".java"],
            "C++": [".cpp", ".cc", ".cxx"],
            "C": [".c"],
            "Go": [".go"],
            "Rust": [".rs"],
            "Ruby": [".rb"],
            "PHP": [".php"],
            "C#": [".cs"],
            "Swift": [".swift"],
            "Kotlin": [".kt"],
            "HTML": [".html", ".htm"],
            "CSS": [".css", ".scss", ".sass"],
        }

        detected_languages = set()

        try:
            for file_path in path.rglob("*"):
                if file_path.is_file():
                    for lang, extensions in language_extensions.items():
                        if any(str(file_path).endswith(ext) for ext in extensions):
                            detected_languages.add(lang)
        except Exception:
            pass

        return list(detected_languages)

    def _detect_frameworks(self, path: Path) -> List[str]:
        """检测使用的框架"""
        frameworks = {
            "React": ["package.json", "react"],
            "Vue": ["package.json", "vue"],
            "Angular": ["package.json", "angular"],
            "Django": ["settings.py", "django"],
            "Flask": ["app.py", "flask"],
            "FastAPI": ["main.py", "fastapi"],
            "Express": ["package.json", "express"],
            "Next.js": ["next.config.js", "next"],
            "TensorFlow": ["requirements.txt", "tensorflow"],
            "PyTorch": ["requirements.txt", "torch"],
        }

        detected_frameworks = []

        try:
            for file_path in path.rglob("*.json"):
                if file_path.is_file():
                    content = file_path.read_text(encoding="utf-8").lower()
                    for framework, (filename, keyword) in frameworks.items():
                        if file_path.name == filename and keyword in content:
                            detected_frameworks.append(framework)

            # 检查Python文件中的框架
            for file_path in path.rglob("*.py"):
                if file_path.is_file():
                    content = file_path.read_text(encoding="utf-8").lower()
                    for framework, (filename, keyword) in frameworks.items():
                        if filename == "settings.py" and keyword in content:
                            detected_frameworks.append(framework)
                        elif keyword in content and framework in [
                            "Django",
                            "Flask",
                            "FastAPI",
                        ]:
                            detected_frameworks.append(framework)

        except Exception:
            pass

        return detected_frameworks

    def _get_key_files(self, path: Path) -> List[str]:
        """获取关键文件"""
        key_patterns = [
            "README*",
            "LICENSE*",
            "*.md",
            "*.txt",
            "Dockerfile",
            "Makefile",
            ".gitignore",
            "requirements.txt",
            "package.json",
            "pyproject.toml",
            "setup.py",
            "Cargo.toml",
            "pom.xml",
            "build.gradle",
        ]

        key_files = []
        try:
            for pattern in key_patterns:
                for file_path in path.glob(pattern):
                    if file_path.is_file():
                        key_files.append(file_path.name)
        except Exception:
            pass

        return key_files[:20]  # 限制数量

    def _get_recent_files(self, path: Path) -> List[str]:
        """获取最近修改的文件"""
        recent_files = []
        try:
            files = []
            for file_path in path.rglob("*"):
                if file_path.is_file() and not file_path.name.startswith("."):
                    try:
                        mtime = file_path.stat().st_mtime
                        files.append((mtime, str(file_path.relative_to(path))))
                    except OSError:
                        continue

            files.sort(reverse=True)
            recent_files = [file for _, file in files[:10]]
        except Exception:
            pass

        return recent_files

    def _get_project_stats(self, path: Path) -> Dict[str, Any]:
        """获取项目统计信息"""
        stats = {}
        try:
            file_count = 0
            total_size = 0
            file_types: Dict[str, int] = {}

            for file_path in path.rglob("*"):
                if file_path.is_file():
                    file_count += 1
                    try:
                        size = file_path.stat().st_size
                        total_size += size

                        ext = file_path.suffix.lower()
                        if ext:
                            file_types[ext] = file_types.get(ext, 0) + 1
                    except OSError:
                        continue

            stats = {
                "file_count": file_count,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "file_types": dict(sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:10]),
            }
        except Exception:
            pass

        return stats

    def _analyze_conversation_patterns(self, messages: List[Dict]) -> Dict[str, Any]:
        """分析对话模式"""
        if not self.enable_conversation_enhancement:
            return {}

        try:
            patterns = {
                "user_intent": self._detect_user_intent(messages),
                "technical_level": self._assess_technical_level(messages),
                "preferred_response_length": self._analyze_response_preferences(messages),
                "topic_keywords": self._extract_keywords(messages),
                "conversation_style": self._detect_conversation_style(messages),
            }

            return patterns
        except Exception:
            return {}

    def _detect_user_intent(self, messages: List[Dict]) -> str:
        """检测用户意图"""
        if not messages:
            return "general"

        user_messages = [
            msg
            for msg in messages
            if (hasattr(msg, "type") and msg.type == "human") or (hasattr(msg, "get") and msg.get("role") == "user")
        ]
        if not user_messages:
            return "general"

        last_message = (
            user_messages[-1].content if hasattr(user_messages[-1], "content") else user_messages[-1].get("content", "")
        ).lower()

        intent_keywords = {
            "coding": ["code", "code", "code", "function", "函数", "代码", "编程"],
            "analysis": ["analyze", "analysis", "分析", "review", "review"],
            "fixing": ["fix", "error", "bug", "修复", "错误", "问题"],
            "learning": ["learn", "explain", "学习", "解释", "教我"],
            "question": ["?", "？", "how", "what", "why", "如何", "什么", "为什么"],
        }

        for intent, keywords in intent_keywords.items():
            if any(keyword in last_message for keyword in keywords):
                return intent

        return "general"

    def _assess_technical_level(self, messages: List[Dict]) -> str:
        """评估技术水平"""
        if not messages:
            return "intermediate"

        all_content = " ".join(
            [
                (msg.content if hasattr(msg, "content") else msg.get("content", ""))
                for msg in messages
                if (hasattr(msg, "type") and msg.type in ["human", "ai"])
                or (hasattr(msg, "get") and msg.get("role") in ["user", "assistant"])
            ]
        ).lower()

        beginner_keywords = ["new", "beginner", "初学者", "新手", "入门", "简单"]
        advanced_keywords = [
            "optimization",
            "architecture",
            "architecture",
            "performance",
            "优化",
            "架构",
            "高级",
        ]

        if any(keyword in all_content for keyword in beginner_keywords):
            return "beginner"
        elif any(keyword in all_content for keyword in advanced_keywords):
            return "advanced"

        return "intermediate"

    def _analyze_response_preferences(self, messages: List[Dict]) -> str:
        """分析响应偏好"""
        assistant_messages = [
            msg
            for msg in messages
            if (hasattr(msg, "type") and msg.type == "ai") or (hasattr(msg, "get") and msg.get("role") == "assistant")
        ]
        if len(assistant_messages) < 2:
            return "medium"

        avg_length = sum(
            len(msg.content if hasattr(msg, "content") else msg.get("content", "")) for msg in assistant_messages
        ) / len(assistant_messages)

        if avg_length < 200:
            return "short"
        elif avg_length > 800:
            return "detailed"

        return "medium"

    def _extract_keywords(self, messages: List[Dict]) -> List[str]:
        """提取关键词"""
        if not messages:
            return []

        # 技术关键词列表
        tech_keywords = [
            "python",
            "javascript",
            "java",
            "react",
            "vue",
            "angular",
            "docker",
            "git",
            "api",
            "database",
            "frontend",
            "backend",
            "devops",
            "testing",
            "bug",
            "feature",
            "refactor",
            "optimize",
            "deploy",
            "security",
        ]

        all_content = " ".join(
            [
                (msg.content if hasattr(msg, "content") else msg.get("content", ""))
                for msg in messages
                if (hasattr(msg, "type") and msg.type in ["human", "ai"])
                or (hasattr(msg, "get") and msg.get("role") in ["user", "assistant"])
            ]
        ).lower()

        found_keywords = [keyword for keyword in tech_keywords if keyword in all_content]

        return found_keywords[:10]  # 限制数量

    def _detect_conversation_style(self, messages: List[Dict]) -> str:
        """检测对话风格"""
        user_messages = [
            msg
            for msg in messages
            if (hasattr(msg, "type") and msg.type == "human") or (hasattr(msg, "get") and msg.get("role") == "user")
        ]
        if not user_messages:
            return "professional"

        last_message = (
            user_messages[-1].content if hasattr(user_messages[-1], "content") else user_messages[-1].get("content", "")
        )

        informal_indicators = ["!", "哈", "呵呵", "哈哈", "😊", "👍", "谢谢"]
        formal_indicators = ["请", "请问", "能否", "可否", "感谢"]

        informal_count = sum(1 for indicator in informal_indicators if indicator in last_message)
        formal_count = sum(1 for indicator in formal_indicators if indicator in last_message)

        if informal_count > formal_count:
            return "casual"
        elif formal_count > informal_count:
            return "formal"

        return "professional"

    def _build_context_enhancement(self, request: ModelRequest) -> str:
        """构建上下文增强信息"""
        context_parts = []

        # 1. 项目信息
        if self.enable_project_analysis:
            workspace = os.getcwd()
            project_info = self._analyze_project_structure(workspace)
            if project_info:
                context_parts.append("## 项目上下文")
                context_parts.append(f"- 项目类型: {project_info.get('type', '未知')}")
                context_parts.append(f"- 编程语言: {', '.join(project_info.get('languages', []))}")
                context_parts.append(f"- 检测框架: {', '.join(project_info.get('frameworks', []))}")
                context_parts.append(f"- 文件统计: {project_info.get('project_stats', {}).get('file_count', 0)} 个文件")

        # 2. 对话模式
        if self.enable_conversation_enhancement:
            messages = request.state.get("messages", [])
            # Convert messages to dict format if needed
            messages_dict: list[dict[Any, Any]] = []
            for msg in messages:
                if isinstance(msg, dict):
                    messages_dict.append(msg)
                else:
                    # Convert message object to dict
                    msg_dict: dict[Any, Any] = {}
                    if hasattr(msg, "content"):
                        msg_dict["content"] = msg.content
                    if hasattr(msg, "type"):
                        msg_dict["type"] = msg.type
                    if hasattr(msg, "role"):
                        msg_dict["role"] = msg.role
                    messages_dict.append(msg_dict)
            conversation_patterns = self._analyze_conversation_patterns(messages_dict)
            if conversation_patterns:
                context_parts.append("\n## 对话上下文")
                context_parts.append(f"- 用户意图: {conversation_patterns.get('user_intent', 'general')}")
                context_parts.append(f"- 技术水平: {conversation_patterns.get('technical_level', 'intermediate')}")
                context_parts.append(f"- 响应偏好: {conversation_patterns.get('preferred_response_length', 'medium')}")

                keywords = conversation_patterns.get("topic_keywords", [])
                if keywords:
                    context_parts.append(f"- 相关技术: {', '.join(keywords)}")

        # 3. 增强建议
        context_parts.append("\n## 上下文增强建议")
        context_parts.append("- 基于项目类型和用户意图，提供针对性的技术建议")
        context_parts.append("- 根据技术水平调整解释的详细程度")
        context_parts.append("- 考虑用户的响应偏好，调整回答长度")

        return "\n".join(context_parts)

    def before_agent(
        self,
        state: AgentState[Any],  # type: ignore[override]
        runtime,
    ) -> dict[str, Any]:  # type: ignore[override]
        """在代理执行前初始化上下文增强"""
        enhanced_context = {
            "project_analyzed": self.enable_project_analysis,
            "user_preferences_enabled": self.enable_user_preferences,
            "conversation_enhancement_enabled": self.enable_conversation_enhancement,
            "initialized_at": time.time(),
        }

        return {
            "enhanced_context": enhanced_context,
            "project_info": {},
            "user_preferences": {},
            "conversation_context": {},
            "messages": [],
        }

    async def abefore_agent(
        self,
        state: AgentState[Any],  # type: ignore[override]
        runtime,
    ) -> dict[str, Any]:  # type: ignore[override]
        """异步：在代理执行前初始化上下文增强"""
        return self.before_agent(state, runtime)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """包装模型调用，注入增强的上下文"""

        # 构建上下文增强
        context_enhancement = self._build_context_enhancement(request)

        # 注入到系统提示中
        if context_enhancement:
            if request.system_prompt:
                request.system_prompt = f"{context_enhancement}\n\n{request.system_prompt}"  # type: ignore[misc, assignment]
            else:
                request.system_prompt = context_enhancement  # type: ignore[misc, assignment]

        # 执行原始请求
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """异步：包装模型调用，注入增强的上下文"""

        # 构建上下文增强
        context_enhancement = self._build_context_enhancement(request)

        # 注入到系统提示中
        if context_enhancement:
            if request.system_prompt:
                request.system_prompt = f"{context_enhancement}\n\n{request.system_prompt}"  # type: ignore[misc, assignment]
            else:
                request.system_prompt = context_enhancement  # type: ignore[misc, assignment]

        # 执行原始请求
        return await handler(request)
