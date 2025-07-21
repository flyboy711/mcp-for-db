import json
import logging
import re
from typing import Dict, Any, Sequence, Union, List
from server.tools.mysql.base import BaseHandler
from mcp import Tool
from mcp.types import TextContent
from server.config.request_context import get_current_database_manager
from server.tools.mysql import ExecuteSQL
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="tools.log")
logger.setLevel(logging.WARNING)


class CollectTableStats(BaseHandler):
    """收集表的元数据、统计信息和数据分布情况的工具"""
    name = "collect_table_stats"
    description = (
        "收集指定表的元数据、统计信息和数据分布情况（如NDV等）"
        "(Collects metadata, statistics, and data distribution information for specified tables)"
    )

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
                    "deep_analysis": {
                        "type": "boolean",
                        "description": "是否执行深度分析（包括直方图统计等）",
                        "default": False
                    },
                    "histogram_bins": {
                        "type": "integer",
                        "description": "直方图的箱数（深度分析时有效）",
                        "default": 10
                    }
                },
                "required": ["table_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """收集表的统计信息"""
        try:
            if "table_name" not in arguments:
                return [TextContent(type="text", text="错误: 缺少表名参数")]

            table_names = arguments["table_name"]
            deep_analysis = arguments.get("deep_analysis", False)
            histogram_bins = arguments.get("histogram_bins", 10)

            # 分割表名并清理
            tables = [name.strip() for name in table_names.split(",") if name.strip()]

            if not tables:
                return [TextContent(type="text", text="错误: 没有有效的表名")]

            # 收集元数据
            metadata = await self.collect_metadata(tables)

            # 收集统计信息
            statistics = await self.collect_statistics(tables)

            # 收集数据分布信息
            distribution = await self.collect_data_distribution(tables, deep_analysis, histogram_bins)

            # 组合结果
            result = {
                "metadata": metadata,
                "statistics": statistics,
                "distribution": distribution
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
                    "details": {
                        "tables": tables if 'tables' in locals() else [],
                        "deep_analysis": deep_analysis,
                        "histogram_bins": histogram_bins
                    }
                }, indent=2, ensure_ascii=False)
            )]

    async def get_mysql_version(self) -> str:
        """获取 MySQL 服务器版本"""
        execute_sql = ExecuteSQL()
        version_query = "SELECT VERSION() AS version"
        try:
            result = await execute_sql.run_tool({"query": version_query})
            # 直接提取结果值
            if result and isinstance(result[0], dict) and "version" in result[0]:
                return result[0]["version"]
            return "unknown"
        except Exception:
            return "unknown"

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
                except Exception:
                    content = item.text
            else:
                content = item

            # 扁平化结果
            if isinstance(content, list):
                parsed_data.extend(content)
            elif isinstance(content, dict):
                parsed_data.append(content)
            else:
                # 处理其他类型（如字符串）
                parsed_data.append({"raw": content})

        return parsed_data

    def parse_tabular_data(self, data: str) -> list:
        """解析表格格式的数据（增强健壮性）"""
        # 移除结果中的ASCII转义序列
        data = re.sub(r'\x1b\[\d+m', '', data)

        # 分割行
        lines = [line.strip() for line in data.split("\n") if line.strip()]
        if not lines:
            return []

        # 检查是否是表格格式（有标题行）
        if "|" in lines[0]:
            # 找到真正的标题行（跳过可能的分隔线）
            header_line = None
            data_lines = []

            for line in lines:
                if "|" in line and not re.match(r'^[-+|]+$', line):
                    if header_line is None:
                        header_line = line
                    else:
                        data_lines.append(line)

            if header_line is None:
                return []

            # 解析表头
            headers = [h.strip() for h in header_line.split("|") if h.strip()]
            rows = []

            # 解析数据行
            for line in data_lines:
                values = [v.strip() for v in line.split("|")]
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

    async def collect_metadata(self, tables: list) -> dict:
        """收集表的元数据信息（增强健壮性）"""
        db_manager = get_current_database_manager()
        config = db_manager.get_current_config()
        execute_sql = ExecuteSQL()

        # 获取 MySQL 版本
        mysql_version = await self.get_mysql_version()
        is_mysql8 = mysql_version.startswith("8.")

        # 构建 IN 条件 - 使用 LOWER 确保大小写不敏感
        table_condition = "','".join([table.lower() for table in tables])

        # 获取表基本信息
        table_info_query = f"""
            SELECT 
                LOWER(TABLE_NAME) AS TABLE_NAME, 
                ENGINE, 
                TABLE_ROWS, 
                AVG_ROW_LENGTH, 
                DATA_LENGTH, 
                INDEX_LENGTH, 
                TABLE_COLLATION
            FROM information_schema.TABLES 
            WHERE TABLE_SCHEMA = '{config['database']}'
            AND LOWER(TABLE_NAME) IN ('{table_condition}')
        """

        # 获取列信息
        columns_info_query = f"""
            SELECT 
                LOWER(TABLE_NAME) AS TABLE_NAME, 
                COLUMN_NAME, 
                {"COLUMN_TYPE" if is_mysql8 else "DATA_TYPE"} AS COLUMN_TYPE,
                IS_NULLABLE, 
                COLUMN_KEY, 
                COLUMN_DEFAULT, 
                EXTRA, 
                COLUMN_COMMENT
            FROM information_schema.COLUMNS 
            WHERE TABLE_SCHEMA = '{config['database']}'
            AND LOWER(TABLE_NAME) IN ('{table_condition}')
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """

        # 获取索引信息 - 修复歧义问题
        indexes_info_query = f"""
            SELECT 
                LOWER(TABLE_NAME) AS TABLE_NAME, 
                INDEX_NAME, 
                GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS COLUMNS,
                NON_UNIQUE, 
                INDEX_TYPE, 
                COMMENT
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = '{config['database']}'
            AND LOWER(TABLE_NAME) IN ('{table_condition}')
            GROUP BY LOWER(TABLE_NAME), INDEX_NAME  -- 明确指定LOWER(TABLE_NAME)
        """

        # 执行查询
        table_info_result = await execute_sql.run_tool({"query": table_info_query})
        columns_info_result = await execute_sql.run_tool({"query": columns_info_query})
        indexes_info_result = await execute_sql.run_tool({"query": indexes_info_query})

        # 解析结果
        table_info_data = self.parse_result(table_info_result)
        columns_info_data = self.parse_result(columns_info_result)
        indexes_info_data = self.parse_result(indexes_info_result)

        # 结构化结果
        metadata = {}
        for table in tables:
            table_lower = table.lower()

            # 找到表的基本信息
            table_info = next(
                (item for item in table_info_data
                 if item.get("TABLE_NAME") == table_lower),
                {}
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
                if item.get("TABLE_NAME") == table_lower
            ]

            # 获取表的索引信息
            indexes = []
            for item in indexes_info_data:
                if item.get("TABLE_NAME") == table_lower:
                    columns_str = item.get("COLUMNS", "")
                    cols = columns_str.split(",") if isinstance(columns_str, str) else columns_str

                    indexes.append({
                        "name": item.get("INDEX_NAME", ""),
                        "columns": cols,
                        "unique": not bool(item.get("NON_UNIQUE", 1)),
                        "type": item.get("INDEX_TYPE", ""),
                        "comment": item.get("COMMENT", "")
                    })

            metadata[table] = {
                "table_info": table_info,
                "columns": columns,
                "indexes": indexes
            }

        return metadata

    async def collect_statistics(self, tables: list) -> dict:
        """收集表的统计信息（兼容 MySQL 5.7 和 8.0）"""
        execute_sql = ExecuteSQL()
        statistics = {}

        # 获取 MySQL 版本
        mysql_version = await self.get_mysql_version()
        is_mysql8 = mysql_version.startswith("8.")

        for table in tables:
            # 获取 SHOW TABLE STATUS 结果
            status_query = f"SHOW TABLE STATUS LIKE '{table}'"
            status_result = await execute_sql.run_tool({"query": status_query})
            status_data = self.parse_show_table_status(status_result)

            # 收集引擎特定统计信息
            engine_stats = {}
            if status_data and status_data[0].get("Engine", "") == "InnoDB":
                # MySQL 8.0 使用新的系统表
                if is_mysql8:
                    innodb_query = f"""
                        SELECT 
                            table_name AS TABLE_NAME,
                            n_rows AS NUM_ROWS,
                            clustered_index_size AS CLUSTERED_INDEX_SIZE,
                            sum_of_other_index_sizes AS OTHER_INDEX_SIZES
                        FROM information_schema.innodb_tables_stats
                        WHERE table_name = '{table}'
                    """
                # MySQL 5.7 使用不同的系统表
                else:
                    innodb_query = f"""
                        SELECT 
                            NAME AS TABLE_NAME,
                            NUM_ROWS,
                            CLUST_INDEX_SIZE AS CLUSTERED_INDEX_SIZE,
                            OTHER_INDEX_SIZE AS OTHER_INDEX_SIZES
                        FROM information_schema.INNODB_SYS_TABLESTATS
                        WHERE NAME LIKE '%/{table}'
                    """

                innodb_result = await execute_sql.run_tool({"query": innodb_query})
                innodb_data = self.parse_result(innodb_result)

                if innodb_data:
                    engine_stats = innodb_data[0]

            # 获取索引统计信息
            index_stats_query = f"SHOW INDEX FROM `{table}`"
            index_stats_result = await execute_sql.run_tool({"query": index_stats_query})
            index_stats_data = self.parse_result(index_stats_result)

            statistics[table] = {
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
        for header in lines[0].split("|")[1:-1]:
            header = header.strip()
            # 处理包含空格的列名
            if " " in header:
                header = header.replace(" ", "_")
            headers.append(header)

        # 解析数据行
        rows = []
        for line in lines[2:]:
            # 跳过分隔线
            if re.match(r'^[-+|]+$', line):
                continue

            values = [v.strip() for v in line.split("|")[1:-1]]
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

    async def collect_data_distribution(self, tables: list, deep_analysis: bool, bins: int) -> dict:
        """收集表的数据分布情况"""
        execute_sql = ExecuteSQL()
        distribution = {}

        for table in tables:
            table_distribution = {
                "column_distinct_counts": {},
                "histograms": {}
            }

            # 获取表的列名 - 使用更可靠的查询
            columns_query = f"""
                SELECT COLUMN_NAME 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = '{table}'
                ORDER BY ORDINAL_POSITION
            """
            columns_result = await execute_sql.run_tool({"query": columns_query})
            columns_data = self.parse_result(columns_result)

            # 提取列名
            columns = []
            for item in columns_data:
                if isinstance(item, dict) and "COLUMN_NAME" in item:
                    columns.append(item["COLUMN_NAME"])

            if not columns:
                distribution[table] = table_distribution
                continue

            # 收集每列的不同值数量
            for column in columns:
                distinct_count_query = f"SELECT COUNT(DISTINCT `{column}`) AS distinct_count FROM `{table}`"
                distinct_count_result = await execute_sql.run_tool({"query": distinct_count_query})
                distinct_count_data = self.parse_result(distinct_count_result)

                # 提取不同值数量
                distinct_count = None
                for item in distinct_count_data:
                    if isinstance(item, dict) and "distinct_count" in item:
                        distinct_count = item["distinct_count"]
                        break

                if distinct_count is not None:
                    table_distribution["column_distinct_counts"][column] = distinct_count

            distribution[table] = table_distribution

        return distribution
