import json
import logging
from typing import Dict, Any, Sequence, List
import re
from mcp import Tool
from mcp.types import TextContent

from server.tools.mysql.base import BaseHandler
from server.config import AppConfigManager
from server.tools.mysql import ExecuteSQL
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="database.log")

execute_sql = ExecuteSQL()


class SlowQueryAnalyzer(BaseHandler):
    name = "analyze_slow_queries"
    description = (
            "分析MySQL慢查询日志，生成优化建议"
            + "(Analyze MySQL slow query logs and generate optimization suggestions)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "number",
                        "description": "慢查询阈值(秒)，默认为1秒",
                        "default": 1
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回的慢查询数量上限",
                        "default": 10
                    }
                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        config = AppConfigManager().get_database_config()
        threshold = arguments.get("threshold", 1)
        limit = arguments.get("limit", 10)

        # 获取慢查询日志路径
        slow_log_path = await self._get_slow_log_path(config)
        if not slow_log_path:
            return [TextContent(type="text", text="无法获取慢查询日志路径")]

        # 解析慢查询日志
        slow_queries = self._parse_slow_log(slow_log_path, threshold)

        # 限制返回数量
        slow_queries = sorted(slow_queries, key=lambda x: x["time"], reverse=True)[:limit]

        # 生成优化建议
        suggestions = self._generate_suggestions(slow_queries, config)

        return [TextContent(type="text", text=suggestions)]

    async def _get_slow_log_path(self, config: Dict) -> str:
        """获取慢查询日志路径"""
        sql = "SHOW VARIABLES LIKE 'slow_query_log_file';"
        result = await execute_sql.run_tool({"query": sql})
        if not result or not result[0].text:
            return ""

        # 解析结果获取日志路径
        lines = result[0].text.strip().split('\n')
        if len(lines) < 2:
            return ""

        parts = lines[1].split('\t')
        if len(parts) < 2:
            return ""

        return parts[1]

    def _parse_slow_log(self, log_path: str, threshold: float) -> List[Dict]:
        """解析慢查询日志，提取超过阈值的SQL语句和执行时间"""
        slow_queries = []
        current_query = {"query": "", "time": 0.0}

        try:
            with open(log_path, "r") as f:
                for line in f:
                    if line.startswith("# Time:"):
                        if current_query["query"] and current_query["time"] >= threshold:
                            slow_queries.append(current_query)
                        current_query = {"query": "", "time": 0.0}
                        # 提取执行时间
                        time_str = re.search(r"# Time: (\d+\.\d+)", line).group(1)
                        current_query["time"] = float(time_str)
                    elif line.startswith("# User@Host:"):
                        continue
                    elif line.startswith("# Query_time:"):
                        continue
                    else:
                        current_query["query"] += line

            # 添加最后一个查询
            if current_query["query"] and current_query["time"] >= threshold:
                slow_queries.append(current_query)

        except Exception as e:
            print(f"解析慢查询日志时出错: {e}")

        return slow_queries

    def _generate_suggestions(self, slow_queries: List[Dict], config: Dict) -> str:
        """生成优化建议"""
        suggestions = "慢查询优化建议:\n"

        for query in slow_queries:
            query_text = query["query"].strip()
            if not query_text:
                continue

            analysis = self._analyze_query(query_text, config)
            suggestions += f"\nSQL (执行时间: {query['time']:.3f}s):\n{query_text}\n"
            suggestions += "建议:\n"
            for i, suggestion in enumerate(analysis, 1):
                suggestions += f"{i}. {suggestion}\n"

        return suggestions

    def _analyze_query(self, query: str, config: Dict) -> List[str]:
        """分析查询语句，生成优化建议"""
        # 简单示例：检查是否缺少WHERE子句
        if "WHERE" not in query.upper() and query.upper().startswith("SELECT"):
            return ["建议添加WHERE子句以限制查询范围"]

        # 检查是否缺少索引
        table_name = self._extract_table_name(query)
        if table_name:
            missing_indexes = self._check_missing_indexes(table_name, query, config)
            if missing_indexes:
                return [f"建议在表 {table_name} 上创建索引: {', '.join(missing_indexes)}"]

        return ["未发现明显优化点"]

    def _extract_table_name(self, query: str) -> str:
        """从SQL语句中提取表名"""
        # 简单实现，仅适用于简单查询
        match = re.search(r"FROM\s+(\w+)", query, re.IGNORECASE)
        if match:
            return match.group(1)
        return ""

    def _check_missing_indexes(self, table_name: str, query: str, config: Dict) -> List[str]:
        """检查查询是否缺少必要的索引"""
        # 实际实现中，应查询information_schema统计数据
        # 这里仅作示例
        if "WHERE" in query.upper() and "ORDER BY" in query.upper():
            return ["idx_combined"]
        elif "WHERE" in query.upper():
            return ["idx_where_columns"]
        return []


########################################################################################################################
########################################################################################################################

# 安全SQL验证模式（仅允许SELECT查询）
SAFE_SELECT_PATTERN = re.compile(r'^\s*SELECT\b', re.IGNORECASE)


class ExplainQuery(BaseHandler):
    name = "explain_query"
    description = (
        "执行SQL查询的EXPLAIN分析，支持传统格式和JSON格式输出"
        "(Perform EXPLAIN analysis on SQL queries, supporting traditional and JSON formats)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要分析的SQL查询语句（仅支持SELECT查询）"
                    },
                    "format": {
                        "type": "string",
                        "description": "输出格式：traditional（传统表格）或json",
                        "default": "traditional",
                        "enum": ["traditional", "json"]
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "查询参数值",
                        "default": []
                    }
                },
                "required": ["query"]
            }
        )

    def validate_query(self, query: str) -> bool:
        """验证查询是否为安全的SELECT查询"""
        return SAFE_SELECT_PATTERN.match(query) is not None

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行查询的EXPLAIN分析"""
        try:
            query = arguments["query"].strip()
            output_format = arguments.get("format", "traditional")
            parameters = arguments.get("parameters", [])

            # 验证查询安全性
            if not self.validate_query(query):
                return [TextContent(type="text", text="错误: 仅支持SELECT查询的分析")]

            # 构建EXPLAIN语句
            if output_format == "json":
                explain_query = f"EXPLAIN FORMAT=JSON {query}"
            else:
                explain_query = f"EXPLAIN {query}"

            execute_sql = ExecuteSQL()

            # 执行EXPLAIN查询
            result = await execute_sql.run_tool({
                "query": explain_query,
                "parameters": parameters
            })

            # 对于JSON格式，尝试美化输出
            if output_format == "json" and result:
                try:
                    # 提取JSON内容
                    json_str = result[0].text
                    # 尝试解析为JSON对象
                    json_obj = json.loads(json_str)
                    # 美化输出
                    pretty_json = json.dumps(json_obj, indent=2, ensure_ascii=False)
                    return [TextContent(type="text", text=pretty_json)]
                except json.JSONDecodeError:
                    # 如果解析失败，返回原始结果
                    return result
            else:
                return result

        except Exception as e:
            logger.error(f"执行EXPLAIN分析失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"执行EXPLAIN分析失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class AnalyzeQueryPerformance(BaseHandler):
    name = "analyze_query_performance"
    description = (
        "分析SQL查询的性能特征，包括执行时间、资源使用等"
        "(Analyze SQL query performance characteristics, including execution time, resource usage, etc.)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要分析的SQL查询语句（仅支持SELECT查询）"
                    },
                    "iterations": {
                        "type": "integer",
                        "description": "执行次数（用于计算平均执行时间）",
                        "default": 5
                    },
                    "parameters": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "查询参数值",
                        "default": []
                    }
                },
                "required": ["query"]
            }
        )

    def validate_query(self, query: str) -> bool:
        """验证查询是否为安全的SELECT查询"""
        return SAFE_SELECT_PATTERN.match(query) is not None

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """分析查询性能"""
        try:
            query = arguments["query"].strip()
            iterations = max(1, min(arguments.get("iterations", 5), 20))  # 限制1-20次
            parameters = arguments.get("parameters", [])

            # 验证查询安全性
            if not self.validate_query(query):
                return [TextContent(type="text", text="错误: 仅支持SELECT查询的分析")]

            execute_sql = ExecuteSQL()
            results = []

            # 1. 执行EXPLAIN分析
            explain_result = await ExplainQuery().run_tool({
                "query": query,
                "format": "traditional",
                "parameters": parameters
            })
            results.append(TextContent(type="text", text="=== 执行计划分析 ==="))
            results.extend(explain_result)

            # 2. 执行性能分析
            performance_data = await self.measure_performance(query, parameters, iterations)
            results.append(TextContent(type="text", text="\n=== 性能指标 ==="))
            results.append(TextContent(type="text", text=performance_data))

            # 3. 执行SHOW PROFILE分析（如果可用）
            try:
                profile_result = await self.run_query_profile(query, parameters)
                results.append(TextContent(type="text", text="\n=== 执行性能剖析 ==="))
                results.append(TextContent(type="text", text=profile_result))
            except Exception as e:
                logger.warning(f"性能剖析不可用: {str(e)}")
                results.append(TextContent(type="text", text="\n警告: 性能剖析功能不可用"))

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
            "parameters": parameters
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
                "parameters": parameters
            })

            # 解析执行时间（假设结果格式为"00:00:00.123456"）
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
        status_result = await execute_sql.run_tool({"query": status_query})

        return (
            f"执行次数: {iterations}\n"
            f"平均执行时间: {avg_time:.6f} 秒\n"
            f"性能指标:\n{status_result[0].text if status_result else '无可用数据'}"
        )

    async def run_query_profile(self, query: str, parameters: list) -> str:
        """执行查询的性能剖析"""
        execute_sql = ExecuteSQL()

        # 启用性能剖析
        await execute_sql.run_tool({"query": "SET profiling = 1"})

        try:
            # 执行查询
            await execute_sql.run_tool({
                "query": query,
                "parameters": parameters
            })

            # 获取剖析结果
            profile_query = "SHOW PROFILES"
            profiles = await execute_sql.run_tool({"query": profile_query})

            if not profiles:
                return "无性能剖析数据"

            # 获取最后一个查询的详细剖析
            last_query_id = profiles[0].text.split('\n')[-1].split()[0]
            profile_detail = await execute_sql.run_tool({
                "query": f"SHOW PROFILE FOR QUERY {last_query_id}"
            })

            return profile_detail[0].text if profile_detail else "无详细剖析数据"

        finally:
            # 禁用性能剖析
            await execute_sql.run_tool({"query": "SET profiling = 0"})

########################################################################################################################
