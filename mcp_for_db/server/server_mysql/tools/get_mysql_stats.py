import json
import logging
import re
from typing import Dict, Any, Sequence, Union, List

from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.common.base import BaseHandler
from mcp import Tool
from mcp.types import TextContent
from mcp_for_db.server.server_mysql.config import get_current_database_manager
from mcp_for_db.server.server_mysql.tools import ExecuteSQL
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


class CollectTableStats(BaseHandler):
    """收集表的元数据、统计信息和数据分布情况的工具"""
    name = "collect_table_stats"
    description = ENHANCED_DESCRIPTIONS.get("collect_table_stats")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要收集统计信息的表名，多个表用逗号分隔"
                    },
                    # "deep_analysis": {
                    #     "type": "boolean",
                    #     "description": "是否执行深度分析（包括直方图统计等）",
                    #     "default": False
                    # },
                    # "histogram_bins": {
                    #     "type": "integer",
                    #     "description": "直方图的箱数（深度分析时有效）",
                    #     "default": 10
                    # }
                },
                "required": ["table_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """收集表的统计信息"""
        try:
            if "table_name" not in arguments:
                return [TextContent(type="text", text="错误: 缺少表名参数")]

            table_name = arguments["table_name"]
            # deep_analysis = arguments.get("deep_analysis", False)
            # histogram_bins = arguments.get("histogram_bins", 10)

            # 收集元数据
            metadata = await self.collect_metadata(table_name)

            # 收集统计信息
            statistics = await self.collect_statistics(table_name)

            # 收集数据分布信息
            # distribution = await self.collect_data_distribution(table_name, deep_analysis, histogram_bins)

            # 组合结果
            result = {
                "metadata": metadata,
                "statistics": statistics,
                # "distribution": distribution
            }

            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, ensure_ascii=False)
            )]

        except Exception as e:
            logger.error(f"收集统计信息失败: {str(e)}", exc_info=True)
            return [TextContent(
                type="text",
                text=json.dumps({
                    "error": f"收集统计信息失败: {str(e)}",
                }, indent=2, ensure_ascii=False)
            )]

    async def get_mysql_version(self) -> str:
        """获取 MySQL 服务器版本"""
        execute_sql = ExecuteSQL()
        version_query = "SELECT VERSION() AS version"
        try:
            result = await execute_sql.run_tool({"query": version_query, "tool_name": "collect_table_stats"})
            # 直接提取结果值
            if result and isinstance(result[0], dict) and "version" in result[0]:
                return result[0]["version"]
            return "unknown"
        except Exception as e:
            return f"unknown: {e}"

    def parse_result(self, result: Sequence[Union[TextContent, dict]]) -> List[dict]:
        """解析查询结果为字典列表"""
        parsed_data = []

        for item in result:
            if isinstance(item, TextContent):
                # 尝试解析文本内容
                try:
                    # 如果已经是字典或列表，直接使用
                    if isinstance(item.text, (dict, list)):
                        content = item.text
                    # 尝试解析为JSON
                    elif item.text.strip().startswith('{') or item.text.strip().startswith('['):
                        content = json.loads(item.text)
                    # 尝试解析为表格格式
                    else:
                        content = self.parse_tabular_data(item.text)
                except RuntimeError:
                    # 尝试直接提取数字值
                    text = item.text.strip()
                    if re.match(r'^\d+$', text):
                        content = int(text)
                    else:
                        content = item.text
            else:
                content = item

            # 扁平化结果
            if isinstance(content, list):
                parsed_data.extend(content)
            elif isinstance(content, dict):
                parsed_data.append(content)
            elif isinstance(content, (int, float)):
                parsed_data.append({"value": content})
            else:
                # 处理其他类型（如字符串）
                parsed_data.append({"raw": content})

        return parsed_data

    def parse_tabular_data(self, data: str) -> list:
        """解析表格格式的数据"""
        # 移除结果中的ASCII转义序列
        data = re.sub(r'\x1b\[\d+m', '', data)

        # 分割行
        lines = [line.strip() for line in data.split("\n") if line.strip()]
        if not lines:
            return []

        # 检查是否是表格格式（有标题行）
        if "|" in lines[0] or "," in lines[0] or re.match(r'^\w+(\s+\w+)*$', lines[0]):
            # 尝试确定分隔符
            if "|" in lines[0]:
                delimiter = "|"
            elif "," in lines[0]:
                delimiter = ","
            else:
                # 没有明显分隔符，可能是单列数据
                delimiter = None

            # 找到真正的标题行（跳过可能的分隔线）
            header_line = None
            data_lines = []

            for line in lines:
                # 如果是分隔线则跳过
                if re.match(r'^[-+|,]+$', line):
                    continue
                if header_line is None:
                    header_line = line
                else:
                    data_lines.append(line)

            if header_line is None:
                return []

            # 解析表头
            if delimiter:
                headers = [h.strip() for h in header_line.split(delimiter) if h.strip()]
            else:
                # 单列数据，使用默认标题
                headers = ["COLUMN_NAME"]

            rows = []

            # 解析数据行
            for line in data_lines:
                # 跳过分隔线
                if re.match(r'^[-+|,]+$', line):
                    continue

                if delimiter:
                    values = [v.strip() for v in line.split(delimiter)]
                else:
                    # 单列数据，直接使用整行
                    values = [line.strip()]

                # 确保值数量与标题匹配
                if len(values) >= len(headers):
                    row = {}
                    for i, header in enumerate(headers):
                        # 处理值可能包含分隔符的情况
                        value = values[i] if i < len(values) else ""
                        # 移除首尾空格和引号
                        value = value.strip().strip('"').strip("'")
                        row[header] = value
                    rows.append(row)
                elif len(headers) == 1 and len(values) == 1:
                    # 单列情况，即使标题只有一个，值也只有一个
                    row = {headers[0]: values[0]}
                    rows.append(row)
            return rows

        # 简单键值对格式
        result = []
        current_row = {}
        for line in lines:
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key, value = [part.strip() for part in parts]
                    current_row[key] = value
            elif current_row:
                result.append(current_row)
                current_row = {}

        if current_row:
            result.append(current_row)

        return result

    async def collect_metadata(self, table_name: str) -> dict:
        """收集表的元数据信息"""
        execute_sql = ExecuteSQL()

        # 获取 MySQL 版本
        mysql_version = await self.get_mysql_version()
        is_mysql8 = mysql_version.startswith("8.")

        # 获取当前数据库
        db_name = get_current_database_manager().get_current_config().get("database")

        # 获取表基本信息
        table_info_query = f"""
            SELECT 
                TABLE_NAME, 
                ENGINE, 
                TABLE_ROWS, 
                AVG_ROW_LENGTH, 
                DATA_LENGTH, 
                INDEX_LENGTH, 
                TABLE_COLLATION
            FROM information_schema.TABLES 
            WHERE TABLE_SCHEMA = '{db_name}' AND TABLE_NAME = '{table_name}'
        """

        # 获取列信息
        columns_info_query = f"""
            SELECT 
                TABLE_NAME, 
                COLUMN_NAME, 
                {"COLUMN_TYPE" if is_mysql8 else "DATA_TYPE"} AS COLUMN_TYPE,
                IS_NULLABLE, 
                COLUMN_KEY, 
                COLUMN_DEFAULT, 
                EXTRA, 
                COLUMN_COMMENT
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = '{db_name}' AND TABLE_NAME = '{table_name}'
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """

        # 获取索引信息
        indexes_info_query = f"""
            SELECT 
                TABLE_NAME, 
                INDEX_NAME, 
                GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS COLUMNS,
                NON_UNIQUE, 
                INDEX_TYPE, 
                COMMENT
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = '{db_name}' AND TABLE_NAME = '{table_name}'
            GROUP BY TABLE_NAME, INDEX_NAME
        """

        # 执行查询
        table_info_result = await execute_sql.run_tool({"query": table_info_query, "tool_name": "collect_table_stats"})
        columns_info_result = await execute_sql.run_tool(
            {"query": columns_info_query, "tool_name": "collect_table_stats"})
        indexes_info_result = await execute_sql.run_tool(
            {"query": indexes_info_query, "tool_name": "collect_table_stats"})

        # 解析结果
        table_info_data = self.parse_result(table_info_result)
        columns_info_data = self.parse_result(columns_info_result)
        indexes_info_data = self.parse_result(indexes_info_result)

        # 结构化结果
        metadata = {}
        # 找到表的基本信息
        table_info = next(
            (item for item in table_info_data
             if item.get("TABLE_NAME") == table_name), {}
        )

        # 获取表的列信息
        columns = [
            {
                "name": item.get("COLUMN_NAME", ""),
                "type": item.get("COLUMN_TYPE", ""),
                "nullable": item.get("IS_NULLABLE", "") == "YES",
                "default": item.get("COLUMN_DEFAULT", ""),
                "key": item.get("COLUMN_KEY", ""),
                "extra": item.get("EXTRA", ""),
                "comment": item.get("COLUMN_COMMENT", "")
            }
            for item in columns_info_data
            if item.get("TABLE_NAME") == table_name
        ]

        # 获取表的索引信息
        indexes = []
        for item in indexes_info_data:
            if item.get("TABLE_NAME") == table_name:
                columns_str = item.get("COLUMNS", "")
                cols = columns_str.split(",") if isinstance(columns_str, str) else columns_str

                indexes.append({
                    "name": item.get("INDEX_NAME", ""),
                    "columns": cols,
                    "unique": not bool(item.get("NON_UNIQUE", 1)),
                    "type": item.get("INDEX_TYPE", ""),
                    "comment": item.get("COMMENT", "")
                })

        metadata[table_name] = {
            "table_info": table_info,
            "columns": columns,
            "indexes": indexes
        }

        return metadata

    async def collect_statistics(self, table_name: str) -> dict:
        """收集表的统计信息（兼容 MySQL 5.7 和 8.0）"""
        execute_sql = ExecuteSQL()
        statistics = {}

        # 获取 MySQL 版本
        mysql_version = await self.get_mysql_version()
        is_mysql8 = mysql_version.startswith("8.")

        # 获取 SHOW TABLE STATUS 结果
        status_query = f"SHOW TABLE STATUS WHERE Name = '{table_name}'"
        status_result = await execute_sql.run_tool({"query": status_query, "tool_name": "collect_table_stats"})
        status_data = self.parse_show_table_status(status_result)

        # 收集引擎特定统计信息
        engine_stats = {}
        if status_data and status_data[0].get("Engine", "") == "InnoDB":
            # 获取当前数据库名
            db_name = get_current_database_manager().get_current_config().get("database")

            if db_name:
                # MySQL 8.0 使用新的系统表
                if is_mysql8:
                    innodb_query = f"""
                        SELECT 
                            n_rows AS NUM_ROWS,
                            clustered_index_size AS CLUSTERED_INDEX_SIZE,
                            sum_of_other_index_sizes AS OTHER_INDEX_SIZES
                        FROM information_schema.innodb_tables_stats
                        WHERE table_name = '{db_name}/{table_name}'
                    """
                # MySQL 5.7 使用不同的系统表
                else:
                    innodb_query = f"""
                        SELECT 
                            NUM_ROWS,
                            CLUST_INDEX_SIZE AS CLUSTERED_INDEX_SIZE,
                            OTHER_INDEX_SIZE AS OTHER_INDEX_SIZES
                        FROM information_schema.INNODB_SYS_TABLESTATS
                        WHERE NAME = '{db_name}/{table_name}'
                    """

                innodb_result = await execute_sql.run_tool({"query": innodb_query, "tool_name": "collect_table_stats"})
                innodb_data = self.parse_result(innodb_result)

                if innodb_data:
                    engine_stats = innodb_data[0]

        # 获取索引统计信息
        index_stats_query = f"SHOW INDEX FROM `{table_name}`"
        index_stats_result = await execute_sql.run_tool(
            {"query": index_stats_query, "tool_name": "collect_table_stats"})
        index_stats_data = self.parse_result(index_stats_result)

        statistics[table_name] = {
            "table_status": status_data[0] if status_data else {},
            "engine_specific": engine_stats,
            "index_stats": index_stats_data
        }

        return statistics

    def parse_show_table_status(self, result: Sequence[TextContent]) -> list:
        """专门解析 SHOW TABLE STATUS 的输出"""
        if not result:
            return []

        # 获取原始文本
        text = "\n".join([item.text for item in result])

        # 分割行
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) < 3:
            return []

        # 解析表头
        headers = []
        # 尝试确定分隔符
        delimiter = "|" if "|" in lines[0] else ","

        for header in lines[0].split(delimiter)[1:-1]:
            header = header.strip()
            # 处理包含空格的列名
            if " " in header:
                header = header.replace(" ", "_")
            headers.append(header)

        # 解析数据行
        rows = []
        for line in lines[2:]:
            # 跳过分隔线
            if re.match(r'^[-+|,]+$', line):
                continue

            values = [v.strip() for v in line.split(delimiter)[1:-1]]
            if len(values) == len(headers):
                row = {}
                for i, header in enumerate(headers):
                    # 处理值可能包含分隔符的情况
                    value = values[i] if i < len(values) else ""
                    # 移除首尾空格和引号
                    value = value.strip().strip('"').strip("'")
                    row[header] = value
                rows.append(row)

        return rows

    async def collect_data_distribution(self, table_name: str, deep_analysis: bool, bins: int) -> dict:
        """收集表的数据分布情况 - 优化版，减少查询次数"""
        execute_sql = ExecuteSQL()
        distribution = {}

        # 获取当前数据库名
        db_name = get_current_database_manager().get_current_config().get("database")

        table_distribution = {
            "column_distinct_counts": {},
            "histograms": {}
        }

        # 获取表的列名 - 使用更可靠的查询
        columns_query = f"""
            SELECT COLUMN_NAME 
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = '{db_name}' 
            AND TABLE_NAME = '{table_name}'
            ORDER BY ORDINAL_POSITION
        """
        columns_result = await execute_sql.run_tool({"query": columns_query, "tool_name": "collect_table_stats"})
        columns_data = self.parse_result(columns_result)

        # 提取列名 - 增强解析逻辑
        columns = []
        for item in columns_data:
            if isinstance(item, dict):
                # 尝试从不同键名中提取列名
                if "COLUMN_NAME" in item:
                    columns.append(item["COLUMN_NAME"])
                elif "column_name" in item:
                    columns.append(item["column_name"])
                elif "Column_name" in item:
                    columns.append(item["Column_name"])
                elif "name" in item:
                    columns.append(item["name"])
            elif isinstance(item, str):
                # 尝试从字符串中提取列名
                lines = item.split("\n")
                if len(lines) > 1:  # 有多行数据
                    for line in lines[1:]:  # 跳过标题行
                        if line.strip():
                            columns.append(line.strip())

        # 去重并过滤空值
        columns = list(set([col for col in columns if col]))

        if not columns:
            distribution[table_name] = table_distribution
            return distribution

        # 优化策略1: 只收集非索引列的不同值数量
        # 获取索引列信息
        index_query = f"""
            SELECT COLUMN_NAME 
            FROM information_schema.STATISTICS 
            WHERE TABLE_SCHEMA = '{db_name}' 
            AND TABLE_NAME = '{table_name}'
        """
        index_result = await execute_sql.run_tool({"query": index_query, "tool_name": "collect_table_stats"})
        index_data = self.parse_result(index_result)

        # 提取索引列名
        indexed_columns = set()
        for item in index_data:
            if isinstance(item, dict) and "COLUMN_NAME" in item:
                indexed_columns.add(item["COLUMN_NAME"])

        # 优化策略2: 使用单个查询获取所有列的不同值数量
        try:
            # 构建单个查询获取所有列的不同值数量
            distinct_count_query = f"""
                SELECT
                    {', '.join([f'COUNT(DISTINCT `{col}`) AS `{col}_distinct`' for col in columns if col not in indexed_columns])}
                FROM `{table_name}`
            """

            # 如果所有列都是索引列，则跳过查询
            if not any(col not in indexed_columns for col in columns):
                distinct_count_data = []
            else:
                distinct_count_result = await execute_sql.run_tool(
                    {"query": distinct_count_query, "tool_name": "collect_table_stats"})
                distinct_count_data = self.parse_result(distinct_count_result)

            # 处理查询结果
            if distinct_count_data and isinstance(distinct_count_data, list) and distinct_count_data:
                # 获取第一行结果（应该只有一行）
                result_row = distinct_count_data[0]

                for col in columns:
                    if col in indexed_columns:
                        # 对于索引列，使用索引统计信息
                        index_stats = next((item for item in index_data if item.get("COLUMN_NAME") == col), {})
                        distinct_count = index_stats.get("Cardinality", None)
                    else:
                        # 对于非索引列，从查询结果中提取
                        col_key = f"{col}_distinct"
                        distinct_count = result_row.get(col_key, None)

                    if distinct_count is not None:
                        table_distribution["column_distinct_counts"][col] = distinct_count
        except Exception as e:
            logger.error(f"批量获取不同值数量失败: {str(e)}")
            # 如果批量查询失败，回退到逐个查询
            for column in columns:
                try:
                    # 对于索引列，使用索引统计信息
                    if column in indexed_columns:
                        index_stats = next((item for item in index_data if item.get("COLUMN_NAME") == column), {})
                        distinct_count = index_stats.get("Cardinality", None)
                        if distinct_count is not None:
                            table_distribution["column_distinct_counts"][column] = distinct_count
                            continue

                    # 对于非索引列，执行查询
                    distinct_count_query = f"SELECT COUNT(DISTINCT `{column}`) AS distinct_count FROM `{table_name}`"
                    distinct_count_result = await execute_sql.run_tool(
                        {"query": distinct_count_query, "tool_name": "collect_table_stats"})
                    distinct_count_data = self.parse_result(distinct_count_result)

                    # 提取不同值数量
                    distinct_count = None
                    for item in distinct_count_data:
                        if isinstance(item, dict):
                            # 尝试从不同键名中提取值
                            if "distinct_count" in item:
                                distinct_count = item["distinct_count"]
                                break
                            elif "DISTINCT_COUNT" in item:
                                distinct_count = item["DISTINCT_COUNT"]
                                break
                            elif "Distinct_count" in item:
                                distinct_count = item["Distinct_count"]
                                break
                            elif "value" in item:
                                distinct_count = item["value"]
                                break
                            elif "raw" in item:
                                # 尝试从原始数据中提取
                                if isinstance(item["raw"], dict):
                                    if "distinct_count" in item["raw"]:
                                        distinct_count = item["raw"]["distinct_count"]
                                        break
                                elif isinstance(item["raw"], str):
                                    # 尝试从字符串中提取数字
                                    match = re.search(r'\d+', item["raw"])
                                    if match:
                                        distinct_count = int(match.group())
                                        break

                    if distinct_count is not None:
                        table_distribution["column_distinct_counts"][column] = distinct_count
                except Exception as e:
                    logger.error(f"获取列 {column} 的不同值数量失败: {str(e)}")
                    continue

        distribution[table_name] = table_distribution

        return distribution
