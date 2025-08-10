from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.common.base import ToolSelector, BaseHandler, ToolRegistry, WorkflowOrchestrator
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="mcp_tools_mysql.log")
logger.setLevel(LOG_LEVEL)


class SmartTool(BaseHandler):
    """支持多工具协同工作的工具"""
    name = "smart_tool"
    description = ENHANCED_DESCRIPTIONS.get("smart_tool")

    # 缓存工具描述以避免递归
    _cached_description = None

    def get_tool_description(self) -> Tool:
        # 如果已经缓存，直接返回
        if SmartTool._cached_description is not None:
            return SmartTool._cached_description

        # 获取所有工具的参数模式
        all_properties = {}

        # 获取所有工具名称（排除自身）
        tool_names = list(ToolRegistry.tools().keys())
        if self.name in tool_names:
            tool_names.remove(self.name)

        for tool_name in tool_names:
            try:
                tool = ToolRegistry.get_tool(tool_name)
                tool_schema = tool.get_tool_description().inputSchema

                # 确保工具有定义属性
                if "properties" not in tool_schema:
                    continue

                for prop, prop_def in tool_schema["properties"].items():
                    # 添加工具名前缀避免参数冲突
                    prefixed_prop = f"{tool_name}.{prop}"
                    all_properties[prefixed_prop] = {
                        "type": prop_def.get("type", "string"),
                        "description": f"[{tool_name}] {prop_def.get('description', '')}"
                    }
            except Exception as e:
                logger.error(f"获取工具 {tool_name} 描述失败: {str(e)}")
                continue

        # 创建描述对象
        tool_desc = Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "用户原始查询语句"
                    },
                    **all_properties  # 包含所有工具的参数
                },
                "required": ["user_query"]
            }
        )

        # 缓存描述
        SmartTool._cached_description = tool_desc
        return tool_desc

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行工具编排，失败时回退到其他工具"""
        try:
            # 尝试使用 smart_tool 执行
            return await self._execute_smart_tool(arguments)
        except Exception as e:
            logger.error(f"工具编排执行失败: {str(e)}")
            # 回退到其他工具
            return await self._fallback_to_other_tools(arguments)

    async def _execute_smart_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行智能工具编排"""
        user_query = arguments.get("user_query", "")

        # 1. 从参数中提取工具特定的参数
        tool_params = {}
        for key, value in arguments.items():
            if "." in key:  # 工具特定参数格式为 tool_name.param_name
                parts = key.split(".", 1)
                if len(parts) < 2:
                    continue

                tool_name, param_name = parts
                if tool_name not in tool_params:
                    tool_params[tool_name] = {}
                tool_params[tool_name][param_name] = value

        # 2. 推荐工具（使用内部工具选择器）
        recommended_tools = ToolSelector.recommend_tools(tool_params)
        logger.info(f"推荐工具: {', '.join(recommended_tools)}")

        # 3. 选择主工具（使用内部工具选择器）
        primary_tool = ToolSelector.select_primary_tool(tool_params, recommended_tools)
        logger.info(f"选择主工具: {primary_tool}")

        # 4. 生成工作流
        try:
            workflow = WorkflowOrchestrator.generate_workflow(primary_tool, tool_params)
            logger.info(f"生成工作流: {[call.name for call in workflow]}")
        except Exception as e:
            logger.error(f"生成工作流失败: {str(e)}")
            raise RuntimeError(f"生成工作流失败: {str(e)}")

        # 5. 执行整个工具链
        try:
            return await ToolRegistry.execute_workflow(workflow)
        except Exception as e:
            logger.exception(f"工具编排失败: {str(e)}")
            raise RuntimeError(f"工具编排失败: {str(e)}")

    async def _fallback_to_other_tools(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """回退到其他工具执行"""
        logger.warning("工具编排失败，尝试回退到其他工具")

        # 1. 尝试直接使用 SQL 执行器
        if "sql_executor.query" in arguments:
            try:
                sql_executor = ToolRegistry.get_tool("sql_executor")
                return await sql_executor.run_tool({
                    "query": arguments["sql_executor.query"],
                    "parameters": arguments.get("sql_executor.parameters", [])
                })
            except Exception as e:
                logger.error(f"SQL执行器回退失败: {str(e)}")

        # 2. 尝试使用表名查询工具
        if "get_table_name.text" in arguments:
            try:
                table_name_tool = ToolRegistry.get_tool("get_table_name")
                return await table_name_tool.run_tool({
                    "text": arguments["get_table_name.text"]
                })
            except Exception as e:
                logger.error(f"表名查询工具回退失败: {str(e)}")

        # 3. 所有回退尝试都失败
        return [TextContent(type="text", text="所有工具执行失败，请检查参数或联系管理员")]
