from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.common.base import BaseHandler
from mcp_for_db.server.server_mysql.tools import ExecuteSQL
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(LOG_LEVEL)


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
            parameters = arguments.get("parameters", [])

            execute_sql = ExecuteSQL()
            results = []

            # 1. 执行EXPLAIN分析
            try:
                explain_result = await execute_sql.run_tool({
                    "query": f"EXPLAIN FORMAT=JSON {query}",
                    "parameters": parameters,
                    "tool_name": "analyze_query_performance"
                })
                results.append(TextContent(type="text", text="=== 执行计划分析 ==="))
                results.extend(explain_result)
            except Exception as e:
                logger.warning(f"EXPLAIN分析失败: {str(e)}")
                results.append(TextContent(type="text", text="=== 执行计划分析 ==="))
                results.append(TextContent(type="text", text=f"EXPLAIN分析失败: {str(e)}"))

            # 2. 执行性能分析
            performance_data = await self.measure_performance(query, parameters, 5)
            results.append(TextContent(type="text", text="\n=== 性能指标 ==="))
            results.append(TextContent(type="text", text=performance_data))

            return results

        except Exception as e:
            logger.error(f"查询性能分析失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"查询性能分析失败: {str(e)}")]

    async def measure_performance(self, query: str, parameters: list, iterations: int) -> str:
        """测量查询性能指标"""
        import time
        execute_sql = ExecuteSQL()

        # 预热执行（确保数据在缓存中）
        try:
            await execute_sql.run_tool({
                "query": query,
                "parameters": parameters,
                "tool_name": "analyze_query_performance"
            })
        except Exception as e:
            logger.warning(f"预热执行失败: {str(e)}")

        # 执行多次计算平均时间
        execution_times = []
        successful_executions = 0

        for i in range(iterations):
            try:
                # 使用 Python 时间测量而不是 SQL
                start_time = time.perf_counter()

                await execute_sql.run_tool({
                    "query": query,
                    "parameters": parameters,
                    "tool_name": "analyze_query_performance"
                })

                end_time = time.perf_counter()
                execution_time = end_time - start_time
                execution_times.append(execution_time)
                successful_executions += 1

            except Exception as e:
                logger.warning(f"第 {i + 1} 次执行失败: {str(e)}")
                continue

        # 计算统计信息
        if execution_times:
            avg_time = sum(execution_times) / len(execution_times)
            min_time = min(execution_times)
            max_time = max(execution_times)
        else:
            avg_time = min_time = max_time = 0

        # 获取查询状态信息
        status_info = await self.get_query_status()

        # 获取表统计信息
        table_stats = await self.get_table_stats(query)

        return (
            f"执行次数: {successful_executions}/{iterations}\n"
            f"平均执行时间: {avg_time:.6f} 秒\n"
            f"最小执行时间: {min_time:.6f} 秒\n"
            f"最大执行时间: {max_time:.6f} 秒\n"
            f"执行时间标准差: {self.calculate_std_dev(execution_times):.6f} 秒\n"
            f"\n{status_info}\n"
            f"{table_stats}"
        )

    async def get_query_status(self) -> str:
        """获取查询相关的状态信息"""
        execute_sql = ExecuteSQL()

        try:
            # 获取处理器状态
            status_result = await execute_sql.run_tool({
                "query": "SHOW SESSION STATUS WHERE Variable_name LIKE 'Handler%' OR Variable_name LIKE 'Select%' OR Variable_name LIKE 'Sort%'",
                "tool_name": "analyze_query_performance"
            })

            if status_result and len(status_result) > 0:
                return f"MySQL 状态指标:\n{status_result[0].text}"
            else:
                return "MySQL 状态指标: 无可用数据"

        except Exception as e:
            logger.warning(f"获取状态信息失败: {str(e)}")
            return f"MySQL 状态指标: 获取失败 - {str(e)}"

    async def get_table_stats(self, query: str) -> str:
        """获取查询涉及表的统计信息"""
        execute_sql = ExecuteSQL()

        try:
            # 从查询中提取表名（简单实现）
            table_name = self.extract_table_name(query)

            if table_name:
                # 获取表统计信息
                stats_query = f"""
                SELECT 
                    table_name,
                    table_rows,
                    data_length,
                    index_length,
                    (data_length + index_length) as total_size
                FROM information_schema.tables 
                WHERE table_name = '{table_name}' 
                AND table_schema = DATABASE()
                """

                stats_result = await execute_sql.run_tool({
                    "query": stats_query,
                    "tool_name": "analyze_query_performance"
                })

                if stats_result and len(stats_result) > 0:
                    return f"表统计信息:\n{stats_result[0].text}"
                else:
                    return f"表统计信息: 表 {table_name} 的统计信息不可用"
            else:
                return "表统计信息: 无法从查询中提取表名"

        except Exception as e:
            logger.warning(f"获取表统计信息失败: {str(e)}")
            return f"表统计信息: 获取失败 - {str(e)}"

    def extract_table_name(self, query: str) -> str:
        """从查询中提取主表名"""
        import re

        # 简单的正则表达式提取 FROM 后的表名
        match = re.search(r'\bFROM\s+(\w+)', query.upper())
        if match:
            return match.group(1).lower()
        return ""

    def calculate_std_dev(self, times: list) -> float:
        """计算标准差"""
        if len(times) < 2:
            return 0.0

        mean = sum(times) / len(times)
        variance = sum((x - mean) ** 2 for x in times) / (len(times) - 1)
        return variance ** 0.5
########################################################################################################################
