import logging
from typing import Dict, Sequence, Any
from server.utils.logger import configure_logger, get_logger

from mcp import Tool
from mcp.types import TextContent

from server.tools.mysql.base import BaseHandler
from server.config import AppConfigManager
from server.tools.mysql import ExecuteSQL

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="get_table_infos.log")

execute_sql = ExecuteSQL()


########################################################################################################################
class GetTableDesc(BaseHandler):
    name = "get_table_desc"
    description = (
        "根据表名搜索数据库中对应的表字段,支持多表查询(Search for table structures in the database based on table names, supporting multi-table queries)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要搜索的表名"
                    }
                },
                "required": ["text"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取指定表的字段结构信息

        参数:
            text (str): 要查询的表名，多个表名以逗号分隔

        返回:
            list[TextContent]: 包含查询结果的TextContent列表
            - 返回表的字段名、字段注释等信息
            - 结果按表名和字段顺序排序
            - 结果以CSV格式返回，包含列名和数据
        """
        try:
            if "text" not in arguments:
                raise ValueError("缺少查询语句")

            text = arguments["text"]

            config = AppConfigManager().get_database_config()
            execute_sql = ExecuteSQL()

            # 将输入的表名按逗号分割成列表
            table_names = [name.strip() for name in text.split(',')]
            # 构建IN条件
            table_condition = "','".join(table_names)

            sql = "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_COMMENT "
            sql += f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = '{config['database']}' "
            sql += f"AND TABLE_NAME IN ('{table_condition}') ORDER BY TABLE_NAME, ORDINAL_POSITION;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql})

        except Exception as e:
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################
class GetTableIndex(BaseHandler):
    name = "get_table_index"
    description = (
        "根据表名搜索数据库中对应的表索引,支持多表查询(Search for table indexes in the database based on table names, supporting multi-table queries)"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要搜索的表名"
                    }
                },
                "required": ["text"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取指定表的索引信息

        参数:
            text (str): 要查询的表名，多个表名以逗号分隔

        返回:
            list[TextContent]: 包含查询结果的TextContent列表
            - 返回表的索引名、索引字段、索引类型等信息
            - 结果按表名、索引名和索引顺序排序
            - 结果以CSV格式返回，包含列名和数据
        """
        try:
            if "text" not in arguments:
                raise ValueError("缺少查询语句")

            text = arguments["text"]

            config = AppConfigManager().get_database_config()
            execute_sql = ExecuteSQL()

            # 将输入的表名按逗号分割成列表
            table_names = [name.strip() for name in text.split(',')]
            # 构建IN条件
            table_condition = "','".join(table_names)

            sql = "SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, NON_UNIQUE, INDEX_TYPE "
            sql += f"FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = '{config['database']}' "
            sql += f"AND TABLE_NAME IN ('{table_condition}') ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;"

            return await execute_sql.run_tool({"query": sql})

        except Exception as e:
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################

class GetTableLock(BaseHandler):
    name = "get_table_lock"
    description = (
        "获取当前mysql服务器行级锁、表级锁情况(Check if there are row-level locks or table-level locks in the current MySQL server  )"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {

                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        use_result = await self.get_table_use(arguments)
        lock_result_5 = await self.get_table_lock_for_mysql5(arguments)
        lock_result_8 = await self.get_table_lock_for_mysql8(arguments)

        # 合并两个结果
        combined_result = []
        combined_result.extend(use_result)
        combined_result.extend(lock_result_5)
        combined_result.extend(lock_result_8)

        return combined_result

    """
        获取表级锁情况
    """

    @staticmethod
    async def get_table_use(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        try:
            sql = "SHOW OPEN TABLES WHERE In_use > 0;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取行级锁情况--mysql5.6
    """

    @staticmethod
    async def get_table_lock_for_mysql5(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        try:
            sql = "SELECT p2.`HOST` 被阻塞方host,  p2.`USER` 被阻塞方用户, r.trx_id 被阻塞方事务id, "
            sql += "r.trx_mysql_thread_id 被阻塞方线程号,TIMESTAMPDIFF(SECOND, r.trx_wait_started, CURRENT_TIMESTAMP) 等待时间, "
            sql += "r.trx_query 被阻塞的查询, l.lock_table 阻塞方锁住的表, m.`lock_mode` 被阻塞方的锁模式, "
            sql += "m.`lock_type` '被阻塞方的锁类型(表锁还是行锁)', m.`lock_index` 被阻塞方锁住的索引, "
            sql += "m.`lock_space` 被阻塞方锁对象的space_id, m.lock_page 被阻塞方事务锁定页的数量, "
            sql += "m.lock_rec 被阻塞方事务锁定记录的数量, m.lock_data 被阻塞方事务锁定记录的主键值, "
            sql += "p.`HOST` 阻塞方主机, p.`USER` 阻塞方用户, b.trx_id 阻塞方事务id,b.trx_mysql_thread_id 阻塞方线程号, "
            sql += "b.trx_query 阻塞方查询, l.`lock_mode` 阻塞方的锁模式, l.`lock_type` '阻塞方的锁类型(表锁还是行锁)',"
            sql += "l.`lock_index` 阻塞方锁住的索引,l.`lock_space` 阻塞方锁对象的space_id,l.lock_page 阻塞方事务锁定页的数量,"
            sql += "l.lock_rec 阻塞方事务锁定行的数量,  l.lock_data 阻塞方事务锁定记录的主键值,"
            sql += "IF(p.COMMAND = 'Sleep', CONCAT(p.TIME, ' 秒'), 0) 阻塞方事务空闲的时间 "
            sql += "FROM information_schema.INNODB_LOCK_WAITS w "
            sql += "INNER JOIN information_schema.INNODB_TRX b ON b.trx_id = w.blocking_trx_id "
            sql += "INNER JOIN information_schema.INNODB_TRX r ON r.trx_id = w.requesting_trx_id "
            sql += "INNER JOIN information_schema.INNODB_LOCKS l ON w.blocking_lock_id = l.lock_id AND l.`lock_trx_id` = b.`trx_id` "
            sql += "INNER JOIN information_schema.INNODB_LOCKS m ON m.`lock_id` = w.`requested_lock_id` AND m.`lock_trx_id` = r.`trx_id` "
            sql += "INNER JOIN information_schema.PROCESSLIST p ON p.ID = b.trx_mysql_thread_id "
            sql += "INNER JOIN information_schema.PROCESSLIST p2 ON p2.ID = r.trx_mysql_thread_id "
            sql += "ORDER BY 等待时间 DESC;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取行级锁情况--mysql8
    """

    @staticmethod
    async def get_table_lock_for_mysql8(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        try:
            sql = "SELECT p2.HOST AS '被阻塞方host',p2.USER AS '被阻塞方用户',r.trx_id AS '被阻塞方事务id', "
            sql += "r.trx_mysql_thread_id AS '被阻塞方线程号',TIMESTAMPDIFF(SECOND, r.trx_wait_started, CURRENT_TIMESTAMP) AS '等待时间',"
            sql += "r.trx_query AS '被阻塞的查询',dlr.OBJECT_SCHEMA AS '被阻塞方锁库',dlr.OBJECT_NAME AS '被阻塞方锁表',"
            sql += "dlr.LOCK_MODE AS '被阻塞方锁模式', dlr.LOCK_TYPE AS '被阻塞方锁类型',dlr.INDEX_NAME AS '被阻塞方锁住的索引',"
            sql += "dlr.LOCK_DATA AS '被阻塞方锁定记录的主键值',p.HOST AS '阻塞方主机',p.USER AS '阻塞方用户',b.trx_id AS '阻塞方事务id',"
            sql += "b.trx_mysql_thread_id AS '阻塞方线程号',b.trx_query AS '阻塞方查询',dlb.LOCK_MODE AS '阻塞方锁模式',"
            sql += "dlb.LOCK_TYPE AS '阻塞方锁类型',dlb.INDEX_NAME AS '阻塞方锁住的索引',dlb.LOCK_DATA AS '阻塞方锁定记录的主键值',"
            sql += "IF(p.COMMAND = 'Sleep', CONCAT(p.TIME, ' 秒'), 0) AS '阻塞方事务空闲的时间' "
            sql += "FROM performance_schema.data_lock_waits w "
            sql += "JOIN performance_schema.data_locks dlr ON w.REQUESTING_ENGINE_LOCK_ID = dlr.ENGINE_LOCK_ID "
            sql += "JOIN performance_schema.data_locks dlb ON w.BLOCKING_ENGINE_LOCK_ID = dlb.ENGINE_LOCK_ID "
            sql += "JOIN information_schema.innodb_trx r ON w.REQUESTING_ENGINE_TRANSACTION_ID = r.trx_id "
            sql += "JOIN information_schema.innodb_trx b ON w.BLOCKING_ENGINE_TRANSACTION_ID = b.trx_id "
            sql += "JOIN information_schema.processlist p ON b.trx_mysql_thread_id = p.ID "
            sql += "JOIN information_schema.processlist p2 ON r.trx_mysql_thread_id = p2.ID "
            sql += "ORDER BY '等待时间' DESC;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################

class GetTableName(BaseHandler):
    name = "get_table_name"
    description = (
        "根据表中文名或表描述搜索数据库中对应的表名(Search for table names in the database based on table comments and descriptions )"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要搜索的表中文名、表描述，仅支持单个查询"
                    }
                },
                "required": ["text"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """根据表的注释搜索数据库中的表名

        参数:
            text (str): 要搜索的表中文注释关键词

        返回:
            list[TextContent]: 包含查询结果的TextContent列表
            - 返回匹配的表名、数据库名和表注释信息
            - 结果以CSV格式返回，包含列名和数据
        """
        try:
            if "text" not in arguments:
                raise ValueError("缺少查询语句")

            text = arguments["text"]
            config = AppConfigManager().get_database_config()
            execute_sql = ExecuteSQL()

            # 使用参数化查询防止SQL注入
            sql = """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_COMMENT LIKE %s;
            """
            params = [config['database'], f"%{text}%"]

            # 安全记录日志（避免记录敏感数据）
            logger.info(f"搜索数据库: {config['database']}, 关键字: {text}")
            logger.debug(f"SQL语句: {sql.strip()}, 参数: {params}")
            logger.info(f"执行的 SQL 语句：{sql}")
            return await execute_sql.run_tool({"query": sql, "parameters": params})

        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################
########################################################################################################################
class GetDatabaseInfo(BaseHandler):
    name = "get_database_info"
    description = "获取数据库基本信息(Get basic database information)"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "include_connection_info": {
                        "type": "boolean",
                        "description": "是否包含连接信息",
                        "default": True
                    }
                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取数据库基本信息"""
        try:
            include_connection = arguments.get("include_connection_info", True)
            config = AppConfigManager().get_database_config()

            # 基础数据库信息查询
            sql = """
                SELECT 
                    'Database' as info_type, 
                    DATABASE() as value
                UNION ALL
                SELECT 
                    'Version' as info_type, 
                    VERSION() as value
                UNION ALL
                SELECT 
                    'Current User' as info_type, 
                    USER() as value
                UNION ALL
                SELECT 
                    'Connection ID' as info_type, 
                    CONNECTION_ID() as value
            """

            # 添加连接信息
            if include_connection:
                sql += """
                UNION ALL
                SELECT 
                    'Host' as info_type, 
                    %s as value
                UNION ALL
                SELECT 
                    'Port' as info_type, 
                    %s as value
                """
                params = [config['host'], config['port']]
            else:
                params = []

            return await ExecuteSQL().run_tool({"query": sql, "parameters": params})

        except Exception as e:
            logger.error(f"获取数据库信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取数据库信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class GetDatabaseTables(BaseHandler):
    name = "get_database_tables"
    description = "获取数据库所有表和对应的表注释(Get all tables and their comments in the database)"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "include_empty_comments": {
                        "type": "boolean",
                        "description": "是否包含无注释的表",
                        "default": True
                    }
                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取数据库所有表和表注释"""
        try:
            include_empty = arguments.get("include_empty_comments", True)
            config = AppConfigManager().get_database_config()
            execute_sql = ExecuteSQL()

            sql = """
                SELECT 
                    TABLE_NAME, 
                    TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s
            """
            params = [config['database']]

            if not include_empty:
                sql += " AND TABLE_COMMENT != ''"

            sql += " ORDER BY TABLE_NAME"

            return await execute_sql.run_tool({"query": sql, "parameters": params})

        except Exception as e:
            logger.error(f"获取数据库表信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取数据库表信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class AnalyzeTableStats(BaseHandler):
    name = "analyze_table_stats"
    description = "分析表统计信息和列统计信息(Analyze table statistics and column statistics)"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要分析的表名"
                    },
                    "include_column_stats": {
                        "type": "boolean",
                        "description": "是否包含列统计信息",
                        "default": True
                    }
                },
                "required": ["table_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """分析表统计信息"""
        try:
            table_name = arguments["table_name"]
            include_columns = arguments.get("include_column_stats", True)

            config = AppConfigManager().get_database_config()

            # 表统计信息查询
            stats_sql = """
                SELECT 
                    TABLE_NAME as '表名',
                    TABLE_ROWS as '行数',
                    ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) as '大小(MB)',
                    ROUND(DATA_LENGTH / 1024 / 1024, 2) as '数据大小(MB)',
                    ROUND(INDEX_LENGTH / 1024 / 1024, 2) as '索引大小(MB)',
                    ENGINE as '存储引擎',
                    TABLE_COLLATION as '字符集'
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_name = %s
            """
            stats_params = [config['database'], table_name]

            # 列统计信息查询
            columns_sql = """
                SELECT 
                    COLUMN_NAME AS '列名',
                    COLUMN_COMMENT AS '列备注',
                    DATA_TYPE AS '数据类型',
                    CHARACTER_MAXIMUM_LENGTH AS '最大长度',
                    NUMERIC_PRECISION AS '数字精度',
                    IS_NULLABLE AS '允许NULL',
                    COLUMN_DEFAULT AS '默认值',
                    COLUMN_KEY AS '键类型'
                FROM information_schema.columns 
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ORDINAL_POSITION
            """
            columns_params = [config['database'], table_name]

            # 执行查询
            stats_result = await ExecuteSQL().run_tool({
                "query": stats_sql,
                "parameters": stats_params
            })

            if include_columns:
                columns_result = await ExecuteSQL().run_tool({
                    "query": columns_sql,
                    "parameters": columns_params
                })
                return stats_result + columns_result
            else:
                return stats_result

        except Exception as e:
            logger.error(f"分析表统计信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"分析表统计信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class CheckTableConstraints(BaseHandler):
    name = "check_table_constraints"
    description = "检查表约束信息(Check table constraints)"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要检查的表名"
                    },
                    "include_foreign_keys": {
                        "type": "boolean",
                        "description": "是否包含外键约束",
                        "default": True
                    },
                    "include_check_constraints": {
                        "type": "boolean",
                        "description": "是否包含检查约束",
                        "default": True
                    }
                },
                "required": ["table_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """检查表约束信息"""
        try:
            table_name = arguments["table_name"]
            include_fk = arguments.get("include_foreign_keys", True)
            include_checks = arguments.get("include_check_constraints", True)

            config = AppConfigManager().get_database_config()

            results = []

            # 外键约束查询
            if include_fk:
                fk_sql = """
                    SELECT 
                        CONSTRAINT_NAME as '约束名',
                        COLUMN_NAME as '列名',
                        REFERENCED_TABLE_NAME as '引用表',
                        REFERENCED_COLUMN_NAME as '引用列',
                        UPDATE_RULE as '更新规则',
                        DELETE_RULE as '删除规则'
                    FROM information_schema.key_column_usage 
                    WHERE table_schema = %s 
                    AND table_name = %s 
                    AND REFERENCED_TABLE_NAME IS NOT NULL
                """
                fk_params = [config['database'], table_name]
                fk_result = await ExecuteSQL().run_tool({
                    "query": fk_sql,
                    "parameters": fk_params
                })
                results.extend(fk_result)

            # 检查约束查询
            if include_checks:
                try:
                    check_sql = """
                        SELECT 
                            CONSTRAINT_NAME as '约束名',
                            CHECK_CLAUSE as '检查条件'
                        FROM information_schema.check_constraints 
                        WHERE constraint_schema = %s 
                        AND table_name = %s
                    """
                    check_params = [config['database'], table_name]
                    check_result = await ExecuteSQL().run_tool({
                        "query": check_sql,
                        "parameters": check_params
                    })
                    results.extend(check_result)
                except Exception:
                    logger.warning("当前MySQL版本不支持检查约束查询")

            return results

        except Exception as e:
            logger.error(f"获取表约束信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取表约束信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
########################################################################################################################
class ShowColumnsTool(BaseHandler):
    name = "mysql_show_columns"
    description = "获取表的列信息"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "表名"
                    },
                    "database": {
                        "type": "string",
                        "description": "数据库名称（可选）"
                    }
                },
                "required": ["table"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取表的列信息"""
        try:
            table = arguments["table"]
            database = arguments.get("database")

            # 构建查询
            if database:
                query = f"SHOW COLUMNS FROM `{database}`.`{table}`"
            else:
                query = f"SHOW COLUMNS FROM `{table}`"

            # 执行查询
            execute_sql = ExecuteSQL()
            return await execute_sql.run_tool({"query": query})

        except Exception as e:
            logger.error(f"获取列信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取列信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
########################################################################################################################
class DescribeTableTool(BaseHandler):
    name = "mysql_describe_table"
    description = "描述表结构"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "表名"
                    },
                    "database": {
                        "type": "string",
                        "description": "数据库名称（可选）"
                    }
                },
                "required": ["table"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """描述表结构"""
        try:
            table = arguments["table"]
            database = arguments.get("database")

            # 构建查询
            if database:
                query = f"DESCRIBE `{database}`.`{table}`"
            else:
                query = f"DESCRIBE `{table}`"

            # 执行查询
            execute_sql = ExecuteSQL()
            return await execute_sql.run_tool({"query": query})

        except Exception as e:
            logger.error(f"描述表结构失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"描述表结构失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
########################################################################################################################
class ShowCreateTableTool(BaseHandler):
    name = "mysql_show_create_table"
    description = "获取表的创建语句"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "表名"
                    },
                    "database": {
                        "type": "string",
                        "description": "数据库名称（可选）"
                    }
                },
                "required": ["table"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取表的创建语句"""
        try:
            table = arguments["table"]
            database = arguments.get("database")

            # 构建查询
            if database:
                query = f"SHOW CREATE TABLE `{database}`.`{table}`"
            else:
                query = f"SHOW CREATE TABLE `{table}`"

            # 执行查询
            execute_sql = ExecuteSQL()
            return await execute_sql.run_tool({"query": query})

        except Exception as e:
            logger.error(f"获取创建语句失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取创建语句失败: {str(e)}")]

########################################################################################################################


########################################################################################################################
