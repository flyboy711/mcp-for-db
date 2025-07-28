import logging
from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent
from server.common import ToolSelector, WorkflowOrchestrator
from server.tools.mysql.base import BaseHandler, ToolRegistry
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


class SmartTool(BaseHandler):
    """支持多工具协同工作"""
    name = "smart_tool"
    description = "根据用户提问，大模型进行参数解析，然后使用该工具会挑选合适的多个工具协同完成任务"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "用户原始查询语句"
                    },
                    "parsed_params": {
                        "type": "object",
                        "description": "大模型解析出的参数",
                        "additionalProperties": True
                    }
                },
                "required": ["user_query"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行智能工具编排"""
        user_query = arguments.get("user_query", "")
        parsed_params = arguments.get("parsed_params", {})

        # 1. 推荐工具
        # recommended_tools = ToolSelector.recommend_tools(user_query)
        # logger.info(f"推荐工具: {', '.join(recommended_tools[:3])}...")
        #
        # # 2. 选择主工具
        # primary_tool = ToolSelector.select_primary_tool(user_query, recommended_tools)
        # logger.info(f"选择主工具: {primary_tool}")

        # 3. 生成工作流
        workflow = WorkflowOrchestrator.generate_workflow(parsed_params)

        # 3. 执行整个工具链
        try:
            return await ToolRegistry.execute_workflow(workflow)
        except RuntimeError as e:
            return [TextContent(type="text", text="智能编排失败")]
