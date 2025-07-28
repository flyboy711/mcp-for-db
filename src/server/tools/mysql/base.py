from typing import Dict, Any, Sequence, Type, ClassVar, List
from mcp.types import TextContent, Tool
from server.common import ToolCall
from server.common.tools import ENHANCED_DESCRIPTIONS


class ToolRegistry:
    """工具注册表，用于管理所有工具实例"""
    _tools: ClassVar[Dict[str, 'BaseHandler']] = {}
    _enhanced_descriptions: ClassVar[Dict[str, str]] = {}

    @classmethod
    def register(cls, tool_class: Type['BaseHandler']) -> Type['BaseHandler']:
        """注册工具类"""
        tool = tool_class()
        cls._tools[tool.name] = tool

        # 自动应用增强描述（如果存在）
        if tool.name in ENHANCED_DESCRIPTIONS:
            tool.enhanced_description = ENHANCED_DESCRIPTIONS[tool.name]

        return tool_class

    @classmethod
    def get_tool(cls, name: str) -> 'BaseHandler':
        """获取工具实例"""
        if name not in cls._tools:
            raise ValueError(f"未知的工具: {name}")
        return cls._tools[name]

    @classmethod
    def get_all_tools(cls) -> list[Tool]:
        """获取所有工具的描述（使用增强描述）"""
        tools = []
        for tool in cls._tools.values():
            # 优先使用增强描述
            description = getattr(tool, 'enhanced_description', None) or tool.description

            # 创建Tool对象
            tool_desc = Tool(
                name=tool.name,
                description=description,
                inputSchema=tool.get_tool_description().inputSchema
            )
            tools.append(tool_desc)
        return tools

    @classmethod
    async def execute_workflow(cls, tool_calls: List[ToolCall]) -> Sequence[TextContent]:
        """执行工具工作流"""
        results = []
        context = {}

        for call in tool_calls:
            tool = cls.get_tool(call.name)

            # 设置上下文
            tool.set_context(context)

            # 执行工具
            tool_result = await tool.run_tool(call.arguments)
            results.extend(tool_result)

            # 更新上下文
            for content in tool_result:
                if isinstance(content, TextContent):
                    context[f"{call.name}.output"] = content.text

        return results


class BaseHandler:
    """工具基类"""
    name: str = ""
    description: str = ""
    enhanced_description: str = ""  # 新增：增强描述字段

    def __init_subclass__(cls, **kwargs):
        """子类初始化时自动注册到工具注册表"""
        super().__init_subclass__(**kwargs)
        if cls.name:  # 只注册有名称的工具
            ToolRegistry.register(cls)

    def __init__(self):
        super().__init__()
        self.context = {}  # 工作流上下文

    def set_context(self, context: Dict[str, Any]):
        """设置工作流上下文"""
        self.context = context

    def get_tool_description(self) -> Tool:
        """获取工具描述（默认实现）"""
        # 优先使用增强描述
        description = self.enhanced_description or self.description

        return Tool(
            name=self.name,
            description=description,
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行工具 - 使用上下文解析参数"""
        # 解析上下文变量
        resolved_args = {}
        for key, value in arguments.items():
            if isinstance(value, str):
                # 替换模板变量
                resolved_value = value
                for var, val in self.context.items():
                    resolved_value = resolved_value.replace(f"{{{var}}}", str(val))
                resolved_args[key] = resolved_value
            else:
                resolved_args[key] = value

        # 调用实际工具逻辑
        return await self._run_tool_impl(resolved_args)

    async def _run_tool_impl(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """实际工具实现（由子类重写）"""
        raise NotImplementedError

########################################################################################################################
########################################################################################################################
