import json
import time
import logging
from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent

from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.server_mysql.resources import QueryLogResource
from mcp_for_db.server.common.base.base_tools import BaseHandler
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


class GetQueryLogs(BaseHandler):
    """获取工具历史查询SQL工具"""
    name = "get_query_logs"
    description = ENHANCED_DESCRIPTIONS.get("get_query_logs")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "要查询的工具名称，如 'execute_sql' 或 'get_table_name'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回的日志条数限制，默认为10",
                        "default": 10
                    },
                    "success_only": {
                        "type": "boolean",
                        "description": "是否只返回成功的查询记录，默认为false",
                        "default": False
                    }
                },
                "required": ["tool_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取指定工具的历史查询记录"""
        try:
            # 获取参数
            tool_name = arguments["tool_name"]
            limit = arguments.get("limit", 10)
            success_only = arguments.get("success_only", False)

            # 验证limit参数
            if limit <= 0:
                return [TextContent(text="Limit must be a positive integer")]

            # 加载日志文件
            logs = QueryLogResource.load_logs(tool_name)

            # 如果没有日志，直接返回空结果
            if not logs:
                return [TextContent(text=f"没有找到 {tool_name} 的查询日志")]

            # 过滤日志
            filtered_logs = []
            for log in logs:
                # 检查工具名称是否匹配
                if log.get("tool_name") != tool_name:
                    continue

                # 检查成功状态
                if success_only and not log.get("success", False):
                    continue

                filtered_logs.append(log)

            # 限制返回数量
            if limit < len(filtered_logs):
                filtered_logs = filtered_logs[-limit:]
                truncated = True
            else:
                truncated = False

            # 格式化结果
            result = []
            for log in filtered_logs:
                # 转换时间戳为可读格式
                timestamp = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(log["timestamp"])
                )

                # 创建结果摘要
                result_summary = log.get("result", "")[:100] + "..." if log.get("result") else ""

                # 构建日志条目
                log_entry = {
                    "timestamp": timestamp,
                    "tool_name": log.get("tool_name", "unknown"),
                    "operation": log.get("operation", ""),
                    "success": log.get("success", False),
                    "result_summary": result_summary
                }

                result.append(log_entry)

            # 返回结果
            response = {
                "tool_name": tool_name,
                "total_logs": len(filtered_logs),
                "logs": result
            }

            if truncated:
                response["message"] = f"结果集过大，仅显示最近 {limit} 条记录"

            return [TextContent(text=json.dumps(response, indent=2))]

        except Exception as e:
            logger.error(f"获取查询日志失败: {str(e)}", exc_info=True)
            return [TextContent(text=f"获取查询日志失败: {str(e)}")]
