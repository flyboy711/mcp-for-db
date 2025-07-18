import logging
from typing import Dict, Any, Sequence, List
import re
from mcp import Tool
from mcp.types import TextContent

from server.config.request_context import get_current_database_manager
from server.tools.mysql.base import BaseHandler
from server.tools.mysql import ExecuteSQL
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="database.log")


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
        db_manager = get_current_database_manager()
        config = db_manager.get_current_config()

        threshold = arguments.get("threshold", 5)
        limit = arguments.get("limit", 10)

        # 获取慢查询日志路径
        slow_log_path = await self.get_slow_log_path(config)
        if not slow_log_path:
            return [TextContent(type="text", text="无法获取慢查询日志路径")]

        # 解析慢查询日志
        slow_queries = await self.parse_slow_log(slow_log_path, threshold)

        # 限制返回数量
        slow_queries = sorted(slow_queries, key=lambda x: x["time"], reverse=True)[:limit]

        # 生成优化建议
        suggestions = self._generate_suggestions(slow_queries, config)

        return [TextContent(type="text", text=suggestions)]

    async def get_slow_log_path(self, config: Dict) -> str:
        """获取慢查询日志路径"""
        execute_sql = ExecuteSQL()
        sql = "SHOW VARIABLES LIKE '%slow_query_log%';"
        result = await execute_sql.run_tool({"query": sql})

        if not result or not result[0].text:
            return ""

        # 获取纯文本内容
        raw_text = result[0].text
        # 标准化处理：去除元数据标记（如果存在）
        if raw_text.startswith('[TextContent(') and raw_text.endswith(')]'):
            # 提取实际内容部分
            content_start = raw_text.find("text='") + 6
            content_end = raw_text.find("',", content_start)
            text_content = raw_text[content_start:content_end]
        else:
            text_content = raw_text

        # 处理换行符：统一转为标准换行符
        normalized_text = text_content.replace('\r\n', '\n').replace('\r', '\n').strip()

        # 按行分割
        lines = normalized_text.split('\n')
        if len(lines) < 2:
            return ""

        # 遍历所有行查找目标值
        slow_query_log_path = ""
        for line in lines:
            # 跳过标题行
            if line.startswith("Variable_name") or not line.strip():
                continue

            # 分割键值对（使用逗号分隔）
            parts = line.split(',', 1)  # 最多分割一次
            if len(parts) < 2:
                continue

            key = parts[0].strip()
            value = parts[1].strip()

            if key == 'slow_query_log_file':
                slow_query_log_path = value
                break

        return slow_query_log_path

    async def parse_slow_log(log_path, threshold=1.0):
        slow_queries = []

        try:
            current_query = {"query": "", "exec_time": 0.0}
            with open(log_path, "r") as f:
                for line in f:
                    # 检测新查询的开始（# Time行）
                    if line.startswith("# Time:"):
                        # 保存上一个查询（如果满足阈值条件）
                        if current_query["query"] and current_query["exec_time"] >= threshold:
                            slow_queries.append(current_query)
                        # 重置当前查询
                        current_query = {"query": "", "exec_time": 0.0}

                    # 提取查询执行时间（关键修复点）
                    elif line.startswith("# Query_time:"):
                        match = re.search(r"Query_time:\s*(\d+\.\d+)", line)
                        if match:
                            current_query["exec_time"] = float(match.group(1))

                    # 忽略其他元信息行
                    elif line.startswith("# User@Host:") or line.startswith("#"):
                        continue

                    # 收集SQL查询语句（关键修复点）
                    else:
                        # 跳过use和SET语句（可选）
                        if not line.startswith(("use ", "SET timestamp=")):
                            current_query["query"] += line.strip() + " "

                # 处理文件末尾的最后一个查询
                if current_query["query"] and current_query["exec_time"] >= threshold:
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

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """分析查询性能"""
        try:
            query = arguments["query"].strip()
            iterations = max(1, min(arguments.get("iterations", 5), 20))  # 限制1-20次
            parameters = arguments.get("parameters", [])

            execute_sql = ExecuteSQL()
            results = []

            # 1. 执行EXPLAIN分析
            explain_result = await execute_sql.run_tool({
                "query": "EXPLAIN FORMAT=JSON " + query,
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
