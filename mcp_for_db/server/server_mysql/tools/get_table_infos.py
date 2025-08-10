from typing import Dict, Sequence, Any

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.server_mysql.config import get_current_database_manager
from mcp_for_db.server.shared.utils import configure_logger, get_logger
from mcp import Tool
from mcp.types import TextContent
from mcp_for_db.server.common.base import BaseHandler
from mcp_for_db.server.server_mysql.tools import ExecuteSQL

logger = get_logger(__name__)
configure_logger(log_filename="mcp_tools_mysql.log")
logger.setLevel(LOG_LEVEL)


class GetTableName(BaseHandler):
    name = "get_table_name"
    description = ENHANCED_DESCRIPTIONS.get("get_table_name")

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

            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()

            sql = "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_COMMENT "
            sql += f"FROM information_schema.TABLES WHERE TABLE_SCHEMA = '{config['database']}' AND TABLE_COMMENT LIKE '%{text}%';"

            # 安全记录日志（避免记录敏感数据）
            logger.info(f"搜索数据库: {config['database']}, 关键字: {text}")
            logger.info(f"执行的 SQL 语句：{sql}")
            return await execute_sql.run_tool({"query": sql, "tool_name": "get_table_name"})

        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################
class GetTableDesc(BaseHandler):
    name = "get_table_desc"
    description = ENHANCED_DESCRIPTIONS.get("get_table_desc")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要搜索的表名"
                    }
                },
                "required": ["table_name"]
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
            if "table_name" not in arguments:
                raise ValueError("缺少查询语句")

            table_name = arguments["table_name"]

            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()

            # 将输入的表名按逗号分割成列表
            table_names = [name.strip() for name in table_name.split(',')]
            # 构建IN条件
            table_condition = "','".join(table_names)

            sql = "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_COMMENT "
            sql += f"FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = '{config['database']}' "
            sql += f"AND TABLE_NAME IN ('{table_condition}') ORDER BY TABLE_NAME, ORDINAL_POSITION;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_table_desc"})

        except Exception as e:
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################
class GetTableIndex(BaseHandler):
    name = "get_table_index"
    description = ENHANCED_DESCRIPTIONS.get("get_table_index")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "要搜索的表名"
                    }
                },
                "required": ["table_name"]
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
            if "table_name" not in arguments:
                raise ValueError("缺少查询语句")

            table_name = arguments["table_name"]

            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()

            # 将输入的表名按逗号分割成列表
            table_names = [name.strip() for name in table_name.split(',')]
            # 构建IN条件
            table_condition = "','".join(table_names)

            sql = "SELECT TABLE_NAME, INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX, NON_UNIQUE, INDEX_TYPE "
            sql += f"FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = '{config['database']}' "
            sql += f"AND TABLE_NAME IN ('{table_condition}') ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;"

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_table_index"})

        except Exception as e:
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################
class GetTableLock(BaseHandler):
    name = "get_table_lock"
    description = ENHANCED_DESCRIPTIONS.get("get_table_lock")

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
                    }
                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        # 获取表级锁情况（所有版本通用）
        use_result = await self.get_table_use()

        # 使用统一的锁查询方法
        lock_result = await self.get_unified_lock_info()

        # 合并结果
        return [*use_result, *lock_result]

    async def get_mysql_major_version(self) -> int:
        """获取 MySQL 主版本号"""
        try:
            db_manager = get_current_database_manager()
            result = await db_manager.execute_query("SELECT VERSION() AS version")
            version_str = result[0]['version'] if result else ""
            return int(version_str.split('.')[0]) if '.' in version_str else 0
        except RuntimeError:
            return 0

    async def get_unified_lock_info(self) -> Sequence[TextContent]:
        """统一的行级锁查询（适用于 MySQL 5.7+ 和 8.0+）"""
        execute_sql = ExecuteSQL()

        # 获取 MySQL 主版本号
        major_version = await self.get_mysql_major_version()

        if major_version >= 8:
            # MySQL 8.0+ 专用查询
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
            logger.info(f"执行的 MySQL 8.x 锁查询语句：{sql}")
        else:
            # MySQL 5.7 专用查询
            sql = """SELECT 
                    r.trx_mysql_thread_id AS '被阻塞进程ID',
                    r.trx_query AS '被阻塞查询',
                    b.trx_mysql_thread_id AS '阻塞进程ID',
                    b.trx_query AS '阻塞查询',
                    TIMESTAMPDIFF(SECOND, r.trx_wait_started, NOW()) AS '等待时间(秒)',
                    CONCAT(k.lock_table, '.', k.lock_index) AS '锁对象',
                    k.lock_index AS '锁定的索引',
                    k.lock_mode AS '等待锁类型',
                    k.lock_mode AS '持有锁类型'
                    FROM information_schema.innodb_lock_waits w
                    JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
                    JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
                    LEFT JOIN information_schema.innodb_locks k ON k.lock_id = w.blocking_lock_id
            """
            logger.info(f"执行的 MySQL 5.7 锁查询语句：{sql}")

        try:
            return await execute_sql.run_tool({"query": sql, "tool_name": "get_table_lock"})
        except Exception as e:
            logger.error(f"锁查询失败: {str(e)}")
            return [TextContent(text=f"锁查询失败: {str(e)}")]

    async def get_table_use(self) -> Sequence[TextContent]:
        """获取表级锁情况（所有版本通用）"""
        execute_sql = ExecuteSQL()
        try:
            sql = "SHOW OPEN TABLES WHERE In_use > 0;"
            logger.info(f"执行的 SQL 语句：{sql}")
            return await execute_sql.run_tool({"query": sql, "tool_name": "get_table_lock"})
        except Exception as e:
            logger.error(f"表级锁查询失败: {str(e)}")
            return [TextContent(text=f"表级锁查询失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class GetDatabaseInfo(BaseHandler):
    name = "get_database_info"
    description = ENHANCED_DESCRIPTIONS.get("get_database_info")

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

            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()

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
                    'Host' as info_type, ? as value
                UNION ALL
                SELECT 
                    'Port' as info_type, ? as value
                """
                params = [config['host'], config['port']]
            else:
                params = []

            return await execute_sql.run_tool({"query": sql, "parameters": params, "tool_name": "get_database_info"})

        except Exception as e:
            logger.error(f"获取数据库信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取数据库信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class GetDatabaseTables(BaseHandler):
    name = "get_database_tables"
    description = ENHANCED_DESCRIPTIONS.get("get_database_tables")

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
        """获取数据库所有表和表注释"""
        try:
            include_empty = True
            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()

            sql = """
                SELECT 
                    TABLE_NAME, 
                    TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = ?
            """
            params = [config['database']]

            if not include_empty:
                sql += " AND TABLE_COMMENT != ''"

            sql += " ORDER BY TABLE_NAME"

            return await execute_sql.run_tool({"query": sql, "parameters": params, "tool_name": "get_database_tables"})

        except Exception as e:
            logger.error(f"获取数据库表信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取数据库表信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class GetTableStats(BaseHandler):
    name = "get_table_stats"
    description = ENHANCED_DESCRIPTIONS.get("get_table_stats")

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
                },
                "required": ["table_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """分析表统计信息"""
        try:
            table_name = arguments["table_name"]
            include_columns = True
            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()

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
                WHERE table_schema = ? AND table_name = ?
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
                WHERE table_schema = ? AND table_name = ?
                ORDER BY ORDINAL_POSITION
            """
            columns_params = [config['database'], table_name]

            # 执行查询
            stats_result = await execute_sql.run_tool({
                "query": stats_sql,
                "parameters": stats_params,
                "tool_name": "get_table_stats"
            })

            if include_columns:
                columns_result = await execute_sql.run_tool({
                    "query": columns_sql,
                    "parameters": columns_params,
                    "tool_name": "get_table_stats"
                })
                return list(stats_result) + list(columns_result)
            else:
                return stats_result

        except Exception as e:
            logger.error(f"分析表统计信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"分析表统计信息失败: {str(e)}")]


########################################################################################################################
########################################################################################################################
class CheckTableConstraints(BaseHandler):
    name = "check_table_constraints"
    description = ENHANCED_DESCRIPTIONS.get("check_table_constraints")

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
                    }
                },
                "required": ["table_name"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """检查表约束信息"""
        try:
            table_name = arguments["table_name"]
            include_fk = True
            include_checks = True

            db_manager = get_current_database_manager()
            config = db_manager.get_current_config()

            execute_sql = ExecuteSQL()
            db_name = config['database']

            results = []

            # 外键约束查询 - 兼容 MySQL 5.7
            if include_fk:
                fk_sql = """
                    SELECT 
                        rc.CONSTRAINT_NAME as '约束名',
                        kcu.COLUMN_NAME as '列名',
                        kcu.REFERENCED_TABLE_NAME as '引用表',
                        kcu.REFERENCED_COLUMN_NAME as '引用列',
                        rc.UPDATE_RULE as '更新规则',
                        rc.DELETE_RULE as '删除规则'
                    FROM information_schema.TABLE_CONSTRAINTS tc
                    JOIN information_schema.KEY_COLUMN_USAGE kcu
                        ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                        AND tc.TABLE_NAME = kcu.TABLE_NAME
                        AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
                        ON tc.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
                        AND tc.TABLE_NAME = rc.TABLE_NAME
                        AND tc.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA
                    WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                    AND tc.TABLE_SCHEMA = ?
                    AND tc.TABLE_NAME = ?
                """
                fk_params = [db_name, table_name]
                fk_result = await execute_sql.run_tool({
                    "query": fk_sql,
                    "parameters": fk_params,
                    "tool_name": "check_table_constraints"
                })
                results.extend(fk_result)

            # 检查约束查询 - 兼容 MySQL 5.7
            if include_checks:
                try:
                    check_sql = """
                        SELECT 
                            CONSTRAINT_NAME as '约束名',
                            '' as '检查条件'  -- MySQL 5.7 没有存储检查条件
                        FROM information_schema.TABLE_CONSTRAINTS
                        WHERE TABLE_SCHEMA = ?
                        AND TABLE_NAME = ?
                        AND CONSTRAINT_TYPE = 'CHECK'
                    """
                    check_params = [db_name, table_name]
                    check_result = await ExecuteSQL().run_tool({
                        "query": check_sql,
                        "parameters": check_params,
                        "tool_name": "check_table_constraints"
                    })
                    results.extend(check_result)
                except Exception as e:
                    # 尝试 MySQL 8.0 的查询（如果失败则跳过）
                    try:
                        check_sql = """
                            SELECT 
                                CONSTRAINT_NAME as '约束名',
                                CHECK_CLAUSE as '检查条件'
                            FROM information_schema.CHECK_CONSTRAINTS 
                            WHERE CONSTRAINT_SCHEMA = ? 
                            AND TABLE_NAME = ?
                        """
                        check_params = [db_name, table_name]
                        check_result = await ExecuteSQL().run_tool({
                            "query": check_sql,
                            "parameters": check_params,
                            "tool_name": "check_table_constraints"
                        })
                        results.extend(check_result)
                    except RuntimeError:
                        logger.warning(f"检查约束查询失败: {e}")

            return results

        except Exception as e:
            logger.error(f"获取表约束信息失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取表约束信息失败: {str(e)}")]

########################################################################################################################
