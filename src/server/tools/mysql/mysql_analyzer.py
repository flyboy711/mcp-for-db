import logging
from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent

from server.common import ENHANCED_DESCRIPTIONS
from server.tools.mysql.base import BaseHandler
from server.tools.mysql import ExecuteSQL
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


########################################################################################################################
class AnalyzeQueryPerformance(BaseHandler):
    name = "analyze_query_performance"
    description = ENHANCED_DESCRIPTIONS.get("analyze_query_performance")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要执行的SQL语句（使用 ? 作为参数占位符）（仅支持SELECT查询）"
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要执行的SQL语句中的参数值列表（按位置顺序依次对应占位符）",
                        "default": []
                    }
                },
                "required": ["query"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """分析查询性能"""
        try:
            query = arguments["query"].strip()
            iterations = 5
            parameters = arguments.get("parameters", [])

            execute_sql = ExecuteSQL()
            results = []

            # 1. 执行EXPLAIN分析
            explain_result = await execute_sql.run_tool({
                "query": "EXPLAIN FORMAT=JSON " + query,
                "parameters": parameters,
                "tool_name": "analyze_query_performance"
            })
            results.append(TextContent(type="text", text="=== 执行计划分析 ==="))
            results.extend(explain_result)

            # 2. 执行性能分析
            performance_data = await self.measure_performance(query, parameters, iterations)
            results.append(TextContent(type="text", text="\n=== 性能指标 ==="))
            results.append(TextContent(type="text", text=performance_data))

            return results

        except Exception as e:
            logger.error(f"查询性能分析失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"查询性能分析失败: {str(e)}")]

    async def measure_performance(self, query: str, parameters: list, iterations: int) -> str:
        """测量查询性能指标"""
        execute_sql = ExecuteSQL()

        # 预热执行（确保数据在缓存中）
        await execute_sql.run_tool({
            "query": query,
            "parameters": parameters,
            "tool_name": "analyze_query_performance"
        })

        # 执行多次计算平均时间
        total_time = 0.0
        for i in range(iterations):
            # 使用SQL内置计时
            timing_query = f"""
                SELECT TIMEDIFF(NOW(6), NOW(6)) as start_time;
                {query};
                SELECT TIMEDIFF(NOW(6), @start_time) as execution_time;
            """
            timing_result = await execute_sql.run_tool({
                "query": timing_query,
                "parameters": parameters,
                "tool_name": "analyze_query_performance"
            })

            # 解析执行时间
            if timing_result and len(timing_result) > 1:
                time_str = timing_result[-1].text.split('\n')[-1].strip()
                if time_str:
                    try:
                        # 将时间字符串转换为秒
                        parts = time_str.split(':')
                        hours = int(parts[0])
                        minutes = int(parts[1])
                        seconds = float(parts[2])
                        total_seconds = hours * 3600 + minutes * 60 + seconds
                        total_time += total_seconds
                    except (ValueError, IndexError):
                        logger.warning(f"无法解析执行时间: {time_str}")

        # 计算平均时间
        avg_time = total_time / iterations if iterations > 0 else 0

        # 获取其他性能指标
        status_query = "SHOW SESSION STATUS LIKE 'Handler%'"
        status_result = await execute_sql.run_tool({"query": status_query, "tool_name": "analyze_query_performance"})

        return (
            f"执行次数: {iterations}\n"
            f"平均执行时间: {avg_time:.6f} 秒\n"
            f"性能指标:\n{status_result[0].text if status_result else '无可用数据'}"
        )
########################################################################################################################
