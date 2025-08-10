from typing import Dict, Any, Sequence, Type, ClassVar, List
from mcp.types import TextContent, Tool

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="mcp_resources.log")
logger.setLevel(LOG_LEVEL)


class ToolCall:
    """表示一个工具调用请求"""

    def __init__(self, name: str, arguments: Dict[str, Any]):
        self.name = name
        self.arguments = arguments

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "arguments": self.arguments
        }


########################################################################################################################
########################################################################################################################
class ToolRegistry:
    """工具注册表，用于管理所有工具实例"""
    _tools: ClassVar[Dict[str, 'BaseHandler']] = {}

    @classmethod
    def register(cls, tool_class: Type['BaseHandler']) -> Type['BaseHandler']:
        """注册工具类"""
        tool = tool_class()
        cls._tools[tool.name] = tool

        logger.info(f"🔧正在注册工具： {tool.name}")
        # 自动应用增强描述（如果存在）
        if tool.name in ENHANCED_DESCRIPTIONS:
            tool.enhanced_description = ENHANCED_DESCRIPTIONS[tool.name]

        return tool_class

    @classmethod
    def get_tool(cls, name: str) -> 'BaseHandler':
        """获取工具实例"""
        logger.info(f"🔧正在请求工具 {name}")
        if name not in cls._tools:
            available_tools = ", ".join(cls._tools.keys())
            logger.warning(f"正在请求的工具未知：{name}")
            raise ValueError(f"未知的工具: {name}，可用工具: {available_tools}")
        return cls._tools[name]

    @classmethod
    def get_all_tools(cls) -> list[Tool]:
        """获取所有工具的描述（使用增强描述）"""
        tools = []
        logger.info(f"当前请求的服务中一共有工具： {len(cls._tools.values())}")
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

        for call in tool_calls:
            try:
                tool = cls.get_tool(call.name)

                # 直接使用参数，不进行模板替换
                tool_result = await tool.run_tool(call.arguments)
                results.extend(tool_result)
            except Exception as e:
                results.append(TextContent(type="text", text=f"执行工具 {call.name} 失败: {str(e)}"))

        return results

    @classmethod
    def tools(cls):
        """获取所有工具实例"""
        return cls._tools


########################################################################################################################
########################################################################################################################
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
        """执行工具 - 直接调用实际工具逻辑"""
        raise NotImplementedError


########################################################################################################################
########################################################################################################################

class WorkflowOrchestrator:
    """工作流编排器 - 根据参数组装工具调用链"""

    @staticmethod
    def generate_workflow(primary_tool: str, tool_params: Dict[str, Dict[str, Any]]) -> List[ToolCall]:
        """
        根据主工具和解析的参数生成工具调用链
        - 添加所有有参数的工具到工作流
        - 确保主工具被包含（即使没有参数）
        - 排除 smart_tool 自身
        """
        workflow = []

        # 1. 添加所有有参数的工具
        for tool_name, params in tool_params.items():
            if params:  # 只添加有参数的工具
                workflow.append(ToolCall(
                    name=tool_name,
                    arguments=params
                ))

        # 2. 确保主工具被包含
        if primary_tool not in tool_params or not tool_params.get(primary_tool):
            # 如果主工具没有参数，添加一个空调用
            workflow.append(ToolCall(
                name=primary_tool,
                arguments={}
            ))

        return workflow


########################################################################################################################
########################################################################################################################
class ToolSelector:
    """工具选择器 - 编排工具内部使用"""

    # 工具优先级映射（从高到低）
    TOOL_PRIORITY = {
        "high": ["sql_executor"],
        "medium": ["get_table_name", "get_table_desc", "get_table_index", "get_table_stats"],
        "low": ["analyze_query_performance", "collect_table_stats", "get_db_health_index_usage"]
    }

    # 工具类别映射
    TOOL_CATEGORIES = {
        "metadata": ["get_table_name", "get_table_desc", "get_table_index", "get_database_info"],
        "execution": ["sql_executor"],
        "analysis": ["sql_executor", "analyze_query_performance", "collect_table_stats", "get_table_stats"],
        "monitoring": ["get_process_list", "get_db_health_running", "get_table_lock"],
        "utility": ["switch_database", "get_chinese_initials", "get_query_logs"]
    }

    # 参数到工具的映射
    PARAM_TO_TOOL_MAPPING = {
        "query": ["sql_executor", "analyze_query_performance"],
        "table_name": ["get_table_desc", "get_table_index", "get_table_stats", "get_table_lock"],
        "text": ["get_table_name", "get_chinese_initials"],
        "host": ["switch_database"],
        "database": ["switch_database"],
        "time_range": ["collect_table_stats"],
        "tool_name": ["get_query_logs", "sql_executor"]
    }

    @staticmethod
    def recommend_tools(tool_params: Dict[str, Dict[str, Any]]) -> List[str]:
        """
        根据解析的参数推荐最合适的工具（排除smart_tool）
        - 优先添加有参数的工具
        - 基于参数类型添加相关工具
        - 基于工具类别添加相关工具
        """
        recommended = set()

        # 1. 添加所有有参数的工具
        for tool_name, params in tool_params.items():
            if tool_name != "smart_tool" and params:
                recommended.add(tool_name)

        # 2. 基于参数类型推荐
        for tool_name, params in tool_params.items():
            if tool_name == "smart_tool":
                continue

            for param_name in params.keys():
                if param_name in ToolSelector.PARAM_TO_TOOL_MAPPING:
                    for tool in ToolSelector.PARAM_TO_TOOL_MAPPING[param_name]:
                        if tool != "smart_tool":
                            recommended.add(tool)

        # 3. 基于工具类别推荐
        if "query" in tool_params.get("sql_executor", {}):
            # 如果有SQL查询，推荐相关分析工具
            for tool in ToolSelector.TOOL_CATEGORIES["analysis"]:
                if tool != "smart_tool":
                    recommended.add(tool)

        # 4. 如果没有推荐工具，返回所有可用工具（排除smart_tool）
        if not recommended:
            all_tools = list(ToolRegistry.tools().keys())
            if "smart_tool" in all_tools:
                all_tools.remove("smart_tool")
            return all_tools

        return list(recommended)

    @staticmethod
    def select_primary_tool(tool_params: Dict[str, Dict[str, Any]], recommended_tools: List[str]) -> str:
        """
        从推荐工具中选择主工具（排除smart_tool）
        - 优先选择有参数的工具作为主工具
        - 其次按优先级选择工具
        - 确保选择有意义的工具
        """
        # 1. 优先选择有参数的工具
        for tool in recommended_tools:
            if tool in tool_params and tool_params[tool]:
                return tool

        # 2. 其次选择高优先级工具
        for tool in ToolSelector.TOOL_PRIORITY["high"]:
            if tool in recommended_tools:
                return tool

        # 3. 再次选择中优先级工具
        for tool in ToolSelector.TOOL_PRIORITY["medium"]:
            if tool in recommended_tools:
                return tool

        # 4. 最后选择低优先级工具
        for tool in ToolSelector.TOOL_PRIORITY["low"]:
            if tool in recommended_tools:
                return tool

        # 5. 如果都没有，返回第一个推荐工具
        return recommended_tools[0] if recommended_tools else "sql_executor"
########################################################################################################################
########################################################################################################################
