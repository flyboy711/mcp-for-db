import logging
from typing import Dict, Any, Sequence, List, Optional, Tuple
from dataclasses import dataclass
import csv
from io import StringIO
from server.utils.logger import get_logger, configure_logger
from mcp import Tool
from mcp.types import TextContent
from server.tools.mysql.base import BaseHandler
from server.resources.log_resource import QueryLogResource

# 导入上下文获取函数
from server.config.request_context import get_current_database_manager

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


@dataclass
class SQLResult:
    """SQL 执行结果封装"""
    success: bool
    message: str
    columns: Optional[List[str]] = None
    rows: Optional[List[Tuple]] = None
    affected_rows: int = 0


async def execute_single_statement(query: str, params: list = None, stream_results: bool = False,
                                   batch_size: int = 1000, tool_name: str = "sql_executor") -> SQLResult:
    """
    使用DatabaseManager执行单条SQL语句（兼容位置参数格式）

    Args:
        query: SQL查询语句，使用 ? 作为参数占位符
        params: 参数值列表（按位置对应占位符）
        stream_results: 是否流式处理大型结果集
        batch_size: 流式处理的批次大小
        tool_name: 调用的工具名称
    """
    # 参数预处理
    final_query = query
    params_dict = None

    # 如果提供了参数列表，转换为命名参数字典并适配查询
    if params is not None:
        # 验证参数数量匹配
        placeholder_count = query.count('?')
        if len(params) != placeholder_count:
            return SQLResult(
                success=False,
                message=f"参数错误: 查询中有 {placeholder_count} 个占位符，但提供了 {len(params)} 个参数值"
            )

        # 转换位置参数为命名参数格式
        params_dict = {}
        for i, value in enumerate(params):
            params_dict[f"param_{i}"] = value

        # 转换查询中的 ? 占位符为命名参数格式
        # IMPORTANT: 这是必要步骤，因为 execute_query 需要命名参数
        for i in range(placeholder_count):
            # 一次性替换所有占位符为命名参数格式
            final_query = final_query.replace('?', f"%(param_{i})s", 1)

    try:
        # 执行查询并获取结果
        db_manager = get_current_database_manager()

        result = await db_manager.execute_query(
            final_query,
            params=params_dict,
            stream_results=stream_results,
            batch_size=batch_size
        )

        # 处理流式结果
        if stream_results and hasattr(result, "__aiter__"):
            collected_rows = []
            async for batch in result:
                collected_rows.extend(batch)
            result = collected_rows

        # 准备返回结果
        sql_result = SQLResult(success=True, message="执行成功")

        # 处理SELECT类型结果
        if isinstance(result, list):
            # 处理非空结果集
            if result and isinstance(result[0], dict):
                # 获取列名（从第一个结果项提取）
                if result and isinstance(result[0], dict):
                    sql_result.columns = list(result[0].keys())
                    sql_result.rows = [tuple(row.values()) for row in result]
                else:
                    sql_result.rows = []

            # 处理特殊返回格式（来自_process_results）
            elif result and "operation" in result[0] and "result_count" in result[0]:
                operation = result[0]['operation']
                count = result[0]['result_count']
                if count > 0:
                    sql_result.message = f"{operation} 查询成功，返回 {count} 条记录"
                else:
                    sql_result.message = f"{operation} 查询成功，但没有匹配记录"
                sql_result.rows = []  # 空结果集

            # 处理DML类型结果
            elif result and isinstance(result[0], dict) and "affected_rows" in result[0]:
                sql_result.message = (
                    f"{result[0]['operation']} 操作成功, "
                    f"影响行数: {result[0]['affected_rows']}"
                )
                sql_result.affected_rows = result[0]['affected_rows']

            # 处理来自_process_dml_result的结果
            elif result and isinstance(result[0], dict) and "operation" in result[0]:
                sql_result.message = (
                    f"{result[0]['operation']} 操作成功, "
                    f"影响行数: {result[0].get('affected_rows', 0)}"
                )
                sql_result.affected_rows = result[0].get('affected_rows', 0)

        QueryLogResource.log_query(tool_name=tool_name, operation=final_query, ret=str(sql_result), success=True)

        return sql_result

    except Exception as e:
        logger.exception(f"执行SQL时出错: {str(e)}")
        QueryLogResource.log_query(tool_name=tool_name, operation=final_query, success=False, error=str(e))
        return SQLResult(success=False, message=f"执行失败: {str(e)}")


class ExecuteSQL(BaseHandler):
    """安全可靠的 MySQL SQL 执行工具（使用DatabaseManager）"""

    name = "sql_executor"
    description = "在MySQL数据库上执行SQL (目前仅支持单条SQL执行)"

    # 结果集最大行数限制
    MAX_RESULT_ROWS = 10000

    def get_tool_description(self) -> Tool:
        """获取工具描述"""
        return Tool(
            name=self.name,
            description=(
                f"{self.description}. 集成了SQL安全分析器、范围检查和权限控制。"
                "只允许使用安全的参数化查询防止SQL注入攻击。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要执行的SQL语句（使用 ? 作为参数占位符）"
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参数值列表（按位置对应占位符）",
                        "default": []
                    },
                    "stream_results": {
                        "type": "boolean",
                        "description": "是否流式处理大型结果集（默认关闭）",
                        "default": False
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "流式处理时每批次返回的行数（默认1000）",
                        "default": 1000
                    },
                    "tool_name": {
                        "type": "string",
                        "description": "如果直接调用SQL执行工具，则工具名为sql_executor，则否还需要传递是谁调用该工具的",
                        "default": "sql_executor"
                    }
                },
                "required": ["query"]
            }
        )

    def format_result(self, result: SQLResult) -> str:
        """格式化SQL执行结果（CSV格式）"""
        if not result.success:
            return result.message

        # 使用CSV模块安全格式化结果
        output = StringIO()
        writer = csv.writer(output)

        try:
            # 添加标题行
            if result.columns:
                writer.writerow(result.columns)

            # 添加数据行（限制最大行数）
            if result.rows:
                for i, row in enumerate(result.rows):
                    if i >= self.MAX_RESULT_ROWS:
                        break
                    # 将None转换为空字符串
                    safe_row = ['' if v is None else str(v) for v in row]
                    writer.writerow(safe_row)

            content = output.getvalue()

            # 添加截断信息
            if result.rows and len(result.rows) > self.MAX_RESULT_ROWS:
                content += f"\n(结果集过大，仅显示前 {self.MAX_RESULT_ROWS} 条记录)"

            return content
        finally:
            output.close()

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行 SQL 工具主入口（使用DatabaseManager）"""
        query = arguments["query"].strip()
        params = arguments.get("parameters", [])
        stream_results = arguments.get("stream_results", False)
        batch_size = arguments.get("batch_size", 1000)
        tool_name = arguments.get("tool_name", "sql_executor")

        # 空查询检查
        if not query:
            return [TextContent(type="text", text="错误: 查询内容为空")]

        try:
            # 执行查询
            sql_result = await execute_single_statement(
                query=query,
                params=params,
                stream_results=stream_results,
                batch_size=batch_size,
                tool_name=tool_name
            )

            # 格式化结果
            formatted = self.format_result(sql_result)
            return [TextContent(type="text", text=formatted)]
        except Exception as e:
            logger.exception(f"执行错误: {str(e)}")
            return [TextContent(type="text", text=f"执行错误: {str(e)}")]
