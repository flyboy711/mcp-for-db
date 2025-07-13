import json
import re
import logging
from typing import Dict, Any, Sequence, List, Tuple
from collections import defaultdict
from server.utils.logger import get_logger, configure_logger
from server.tools.mysql.base import BaseHandler
from server.tools.mysql import ExecuteSQL
from mcp import Tool
from mcp.types import TextContent

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="index_advisor.log")


class IndexAdvisor(BaseHandler):
    """MySQL索引优化顾问工具"""
    name = "mysql_index_advisor"
    description = (
        "分析SQL查询语句，基于数据库元数据和统计信息推荐最佳索引方案"
        "(Analyze SQL queries and recommend optimal index strategies based on database metadata and statistics)"
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
                        "description": "需要优化的SQL查询语句"
                    },
                    "analyze_mode": {
                        "type": "string",
                        "enum": ["quick", "deep"],
                        "description": "分析模式: quick(快速), deep(深度分析)",
                        "default": "quick"
                    },
                    "max_recommendations": {
                        "type": "integer",
                        "description": "最多推荐的索引数量",
                        "default": 3
                    }
                },
                "required": ["query"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行索引优化分析"""
        try:
            query = arguments["query"]
            analyze_mode = arguments.get("analyze_mode", "quick")
            max_recommendations = arguments.get("max_recommendations", 3)

            # 解析查询语句
            tables, columns = self.parse_query(query)
            if not tables:
                return [TextContent(type="text", text="错误: 无法从查询中识别表名")]

            logger.info(f"分析查询: {query[:100]}...")
            logger.info(f"涉及表: {tables}, 涉及列: {columns}")

            # 收集元数据和统计信息
            metadata = await self.collect_metadata(tables)
            statistics = await self.collect_statistics(tables, columns, analyze_mode == "deep")

            # 分析查询执行计划
            explain_plan = await self.analyze_query_plan(query)

            # 生成索引建议
            recommendations = await self.generate_recommendations(
                tables, columns, metadata, statistics, explain_plan, max_recommendations
            )

            # 生成优化报告
            report = self.generate_report(query, tables, columns, recommendations, explain_plan)
            return [TextContent(type="text", text=report)]

        except Exception as e:
            logger.error(f"索引优化失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"索引优化失败: {str(e)}")]

    def parse_query(self, query: str) -> Tuple[List[str], List[str]]:
        """解析SQL查询语句，提取关键信息"""
        # 提取表名
        table_pattern = re.compile(r'\b(?:FROM|JOIN)\s+(\w+)\b', re.IGNORECASE)
        tables = list(set(table_pattern.findall(query)))

        # 提取列名
        column_pattern = re.compile(r'\b(?:WHERE|ON|SET|HAVING|GROUP BY|ORDER BY)\s+([\w\.,\(\)\s=<>!]+)',
                                    re.IGNORECASE)
        column_clauses = column_pattern.findall(query)

        # 提取列名
        columns = []
        for clause in column_clauses:
            # 去除函数调用和运算符
            clean_clause = re.sub(r'\b\w+\(', '', clause)
            clean_clause = re.sub(r'[=<>!]', ' ', clean_clause)
            columns.extend(re.findall(r'\b(\w+)\b', clean_clause))

        return list(set(tables)), list(set(columns))

    async def collect_metadata(self, tables: List[str]) -> Dict[str, Any]:
        """收集数据库元数据：表结构、现有索引等"""
        metadata = {"tables": {}, "indexes": {}}
        execute_sql = ExecuteSQL()

        # 获取表结构信息
        for table in tables:
            # 获取表基本信息
            table_info = await execute_sql.run_tool({
                "query": f"""
                    SELECT 
                        TABLE_NAME, ENGINE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}'
                """
            })
            metadata["tables"][table] = table_info[0].text if table_info else {}

            # 获取表索引信息
            indexes = await execute_sql.run_tool({
                "query": f"SHOW INDEX FROM `{table}`"
            })
            metadata["indexes"][table] = indexes[0].text if indexes else ""

        return metadata

    async def collect_statistics(self, tables: List[str], columns: List[str], deep: bool) -> Dict[str, Any]:
        """收集表和列的统计信息"""
        statistics = {"tables": {}, "columns": {}}
        execute_sql = ExecuteSQL()

        for table in tables:
            # 表级统计信息
            table_stats = await execute_sql.run_tool({
                "query": f"SHOW TABLE STATUS LIKE '{table}'"
            })
            statistics["tables"][table] = table_stats[0].text if table_stats else {}

            # 列级统计信息
            statistics["columns"][table] = {}
            for column in columns:
                if column not in statistics["columns"][table]:
                    # 基本列信息
                    col_info = await execute_sql.run_tool({
                        "query": f"""
                            SELECT 
                                COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY
                            FROM information_schema.COLUMNS
                            WHERE TABLE_SCHEMA = DATABASE() 
                                AND TABLE_NAME = '{table}' 
                                AND COLUMN_NAME = '{column}'
                        """
                    })
                    statistics["columns"][table][column] = col_info[0].text if col_info else {}

                    # 深度分析模式下收集更多统计信息
                    if deep:
                        # 收集列的基数（不同值数量）
                        distinct_count = await execute_sql.run_tool({
                            "query": f"SELECT COUNT(DISTINCT `{column}`) FROM `{table}`"
                        })
                        statistics["columns"][table][column]["distinct_count"] = distinct_count[
                            0].text if distinct_count else 0

        return statistics

    async def analyze_query_plan(self, query: str) -> Dict[str, Any]:
        """分析查询执行计划"""
        execute_sql = ExecuteSQL()
        explain_result = await execute_sql.run_tool({
            "query": f"EXPLAIN FORMAT=JSON {query}"
        })
        return json.loads(explain_result[0].text) if explain_result else {}

    async def generate_recommendations(
            self,
            tables: List[str],
            columns: List[str],
            metadata: Dict[str, Any],
            statistics: Dict[str, Any],
            explain_plan: Dict[str, Any],
            max_recommendations: int
    ) -> List[Dict[str, Any]]:
        """生成索引优化建议"""
        recommendations = []

        # 分析查询中的关键列（WHERE, JOIN, ORDER BY, GROUP BY）
        key_columns = self.identify_key_columns(tables, columns, explain_plan)

        for table in tables:
            if table not in key_columns:
                continue

            # 获取表的现有索引
            existing_indexes = self.get_existing_indexes(table, metadata)

            # 识别缺失索引的列
            missing_index_cols = self.identify_missing_index_columns(table, key_columns[table], existing_indexes)

            if not missing_index_cols:
                continue

            # 生成索引建议
            table_recommendations = self.generate_table_recommendations(
                table, missing_index_cols, statistics, max_recommendations
            )
            recommendations.extend(table_recommendations)

        # 按收益评分排序
        recommendations.sort(key=lambda x: x.get("benefit_score", 0), reverse=True)
        return recommendations[:max_recommendations]

    def identify_key_columns(self, tables: List[str], columns: List[str], explain_plan: Dict[str, Any]) -> Dict[
        str, List[str]]:
        """识别查询中的关键列（基于执行计划）"""
        key_columns = defaultdict(list)

        # 从执行计划中提取关键列
        if "query_block" in explain_plan:
            plan = explain_plan["query_block"]
            # 提取访问的列
            if "table" in plan:
                table = plan["table"].get("table_name", "")
                if table in tables:
                    key_columns[table].extend(columns)

            # 提取连接条件
            if "nested_loop" in plan:
                for join in plan["nested_loop"]:
                    table = join.get("table", {}).get("table_name", "")
                    if table in tables:
                        key_columns[table].extend(columns)

        # 如果没有执行计划信息，则使用所有列
        if not key_columns:
            for table in tables:
                key_columns[table] = columns

        return key_columns

    def get_existing_indexes(self, table: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """获取表的现有索引"""
        indexes = []
        if table in metadata.get("indexes", {}):
            # 解析SHOW INDEX的输出
            index_lines = metadata["indexes"][table].split("\n")
            if len(index_lines) > 1:
                headers = [h.strip() for h in index_lines[0].split("|") if h.strip()]
                for line in index_lines[1:]:
                    values = [v.strip() for v in line.split("|") if v.strip()]
                    if len(values) == len(headers):
                        index_info = dict(zip(headers, values))
                        indexes.append({
                            "name": index_info.get("Key_name", ""),
                            "columns": [index_info.get("Column_name", "")],
                            "unique": index_info.get("Non_unique", "0") == "0"
                        })
        return indexes

    def identify_missing_index_columns(self, table: str, key_columns: List[str],
                                       existing_indexes: List[Dict[str, Any]]) -> List[str]:
        """识别需要索引的列"""
        missing_columns = []

        for column in key_columns:
            # 检查列是否已有索引
            has_index = any(
                column in index["columns"] for index in existing_indexes
            )

            if not has_index:
                missing_columns.append(column)

        return missing_columns

    def generate_table_recommendations(
            self,
            table: str,
            columns: List[str],
            statistics: Dict[str, Any],
            max_recommendations: int
    ) -> List[Dict[str, Any]]:
        """为表生成索引建议"""
        recommendations = []

        # 单列索引建议
        for column in columns[:max_recommendations]:
            recommendations.append(self.create_index_recommendation(table, [column], statistics))

        # 多列组合索引建议（如果有多个列）
        if len(columns) > 1 and len(recommendations) < max_recommendations:
            # 按选择性排序（高选择性列优先）
            sorted_columns = sorted(
                columns,
                key=lambda col: self.get_column_selectivity(table, col, statistics),
                reverse=True
            )
            # 取前2-3列的组合
            if len(sorted_columns) >= 2:
                recommendations.append(self.create_index_recommendation(table, sorted_columns[:2], statistics))
            if len(sorted_columns) >= 3 and len(recommendations) < max_recommendations:
                recommendations.append(self.create_index_recommendation(table, sorted_columns[:3], statistics))

        return recommendations

    def create_index_recommendation(
            self,
            table: str,
            columns: List[str],
            statistics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建单个索引建议"""
        index_name = f"idx_{table}_{'_'.join(columns)}"[:64]
        create_sql = f"CREATE INDEX `{index_name}` ON `{table}` ({', '.join([f'`{c}`' for c in columns])})"

        return {
            "table": table,
            "columns": columns,
            "create_sql": create_sql,
            "benefit_score": self.estimate_benefit(table, columns, statistics),
            "estimated_size": self.estimate_index_size(table, columns, statistics)
        }

    def get_column_selectivity(self, table: str, column: str, statistics: Dict[str, Any]) -> float:
        """获取列的选择性估计"""
        col_stats = statistics.get("columns", {}).get(table, {}).get(column, {})

        # 如果有不同值数量，计算选择性
        if "distinct_count" in col_stats:
            table_rows = statistics.get("tables", {}).get(table, {}).get("Rows", 0)
            if table_rows > 0:
                return float(col_stats["distinct_count"]) / table_rows

        # 启发式规则：基于数据类型
        col_type = col_stats.get("Type", "").lower()
        if 'int' in col_type:
            return 0.8
        if 'date' in col_type or 'time' in col_type:
            return 0.7
        if 'bool' in col_type or 'enum' in col_type:
            return 0.3

        return 0.5  # 默认值

    def estimate_index_size(self, table: str, columns: List[str], statistics: Dict[str, Any]) -> float:
        """估算索引大小（MB）"""
        table_stats = statistics.get("tables", {}).get(table, {})
        if not table_stats:
            return 0.0

        row_count = table_stats.get("Rows", 0)
        if row_count == 0:
            return 0.0

        # 估算列平均大小
        col_sizes = []
        for col in columns:
            col_stats = statistics.get("columns", {}).get(table, {}).get(col, {})
            col_type = col_stats.get("Type", "").lower()

            if 'int' in col_type:
                col_size = 4
            elif 'bigint' in col_type:
                col_size = 8
            elif 'date' in col_type or 'time' in col_type:
                col_size = 8
            elif 'char' in col_type:
                # 从char(XX)中提取大小
                size_match = re.search(r'char\((\d+)\)', col_type)
                col_size = int(size_match.group(1)) if size_match else 32
            else:
                col_size = 32  # 保守估计

            col_sizes.append(col_size)

        # 索引大小估算（包含B-tree开销）
        total_col_size = sum(col_sizes)
        index_size = (total_col_size + 20) * row_count * 1.5 / (1024 * 1024)
        return round(index_size, 2)

    def estimate_benefit(self, table: str, columns: List[str], statistics: Dict[str, Any]) -> float:
        """估算索引带来的性能收益（0-10分）"""
        benefit = 5.0  # 基础收益

        # 1. 列的选择性
        for col in columns:
            selectivity = self.get_column_selectivity(table, col, statistics)
            benefit += selectivity * 1.5

        # 2. 表大小因子
        table_rows = statistics.get("tables", {}).get(table, {}).get("Rows", 0)
        if table_rows > 1000000:  # 大表
            benefit += 2.0
        elif table_rows > 100000:  # 中表
            benefit += 1.0

        return min(max(round(benefit, 1), 10.0))

    def generate_report(
            self,
            query: str,
            tables: List[str],
            columns: List[str],
            recommendations: List[Dict[str, Any]],
            explain_plan: Dict[str, Any]
    ) -> str:
        """生成优化报告"""
        report = f"# MySQL索引优化顾问报告\n\n"
        report += f"**分析查询**:\n```sql\n{query}\n```\n\n"

        report += "## 查询分析摘要\n"
        report += f"- 涉及的表: {', '.join(tables)}\n"
        report += f"- 涉及的列: {', '.join(columns)}\n"

        if explain_plan:
            report += "\n## 查询执行计划分析\n"
            report += self.format_explain_plan(explain_plan)

        if not recommendations:
            report += "\n## 索引优化建议\n"
            report += "未发现需要添加的索引。现有索引已足够高效。\n"
            return report

        report += "\n## 索引优化建议\n"
        report += "以下是根据查询模式、数据分布和现有索引结构推荐的索引方案:\n\n"

        for i, rec in enumerate(recommendations, 1):
            report += f"### 建议 #{i}: {rec['table']} 表优化\n"
            report += f"**推荐索引**: `{', '.join(rec['columns'])}`\n"
            report += f"**创建语句**:\n```sql\n{rec['create_sql']};\n```\n"
            report += f"**预估索引大小**: {rec['estimated_size']} MB\n"
            report += f"**优化收益评分**: {rec['benefit_score']}/10.0\n"
            report += "\n"

        report += "\n## 优化实施建议\n"
        report += ("1. 在测试环境中创建推荐索引并验证性能提升\n"
                   "2. 优先实施收益评分高的索引\n"
                   "3. 监控实际查询性能，特别是高并发场景\n"
                   "4. 定期分析索引使用情况 (SHOW INDEX_STATISTICS)\n"
                   "5. 删除未使用或重复的索引以减少写开销\n")

        report += "\n> **注意**: 索引优化需结合具体业务场景测试验证"

        return report

    def format_explain_plan(self, plan: dict) -> str:
        """格式化EXPLAIN输出为易读文本"""
        if not plan or 'query_block' not in plan:
            return "无法解析查询计划"

        output = ""

        def process_node(node, depth=0):
            nonlocal output
            indent = "  " * depth

            # 节点基本信息
            node_type = node.get('operation', 'UNKNOWN')
            table = node.get('table', '')
            access_type = node.get('access_type', '')
            key = node.get('key', '')
            rows = node.get('rows', 0)
            filtered = node.get('filtered', 100)
            cost_info = node.get('cost_info', {})
            cost = cost_info.get('query_cost', '?')

            output += f"{indent}- **{node_type}**"
            if table:
                output += f" on `{table}`"
            if access_type:
                output += f" ({access_type})"
            if key:
                output += f" using index `{key}`"
            output += "\n"

            output += f"{indent}  - 预估行数: {rows}"
            output += f" | 过滤后: {filtered}%"
            output += f" | 预估成本: {cost}\n"

            # 处理子节点
            for child in node.get('children', []):
                process_node(child, depth + 1)

        # 处理主查询块
        process_node(plan['query_block'])

        return output
