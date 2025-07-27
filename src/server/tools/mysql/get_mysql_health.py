import logging
from typing import Dict, Any, Sequence
from server.config.request_context import get_current_database_manager
from server.utils.logger import configure_logger, get_logger
from mcp import Tool
from mcp.types import TextContent
from server.tools.mysql.base import BaseHandler
from server.tools.mysql import ExecuteSQL

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


########################################################################################################################
class GetDBHealthRunning(BaseHandler):
    name = "get_db_health_running"
    description = (
        "获取当前 MySQL 的健康状态(Analyze MySQL health status )"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        # lock_result = await self.get_lock(arguments)
        processlist_result = await self.get_processlist(arguments)
        status_result = await self.get_status(arguments)
        trx_result = await self.get_trx(arguments)

        # 合并结果
        combined_result = []
        combined_result.extend(processlist_result)
        # combined_result.extend(lock_result)
        combined_result.extend(trx_result)
        combined_result.extend(status_result)

        return combined_result

    """
        获取连接情况
    """

    async def get_processlist(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:
            sql = "SHOW FULL PROCESSLIST;SHOW VARIABLES LIKE 'max_connections';"

            logger.info(f"执行的 SQL 语句：{sql}")
            return await execute_sql.run_tool({"query": sql, "tool_name": "get_db_health_running"})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取运行情况
    """

    async def get_status(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:
            sql = "SHOW ENGINE INNODB STATUS;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_db_health_running"})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取事务情况
    """

    async def get_trx(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:
            sql = "SELECT * FROM INFORMATION_SCHEMA.INNODB_TRX;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_db_health_running"})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取锁情况
    """

    async def get_lock(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:

            results = []

            # 所有版本通用的表级锁查询
            show_open_tables = "SHOW OPEN TABLES WHERE In_use > 0;"
            open_tables_result = await execute_sql.run_tool(
                {"query": show_open_tables, "tool_name": "get_db_health_running"})
            results.extend(open_tables_result)

            # 根据版本选择行级锁查询

            lock_sql = """
                    SELECT 
                        r.trx_mysql_thread_id AS '被阻塞进程ID',
                        r.trx_query AS '被阻塞查询',
                        b.trx_mysql_thread_id AS '阻塞进程ID',
                        b.trx_query AS '阻塞查询',
                        TIMESTAMPDIFF(SECOND, r.trx_wait_started, NOW()) AS '等待时间(秒)',
                        l.lock_table AS '锁对象'
                    FROM information_schema.innodb_lock_waits w
                    JOIN information_schema.innodb_trx b ON b.trx_id = w.blocking_trx_id
                    JOIN information_schema.innodb_trx r ON r.trx_id = w.requesting_trx_id
                    JOIN information_schema.innodb_locks l ON w.blocking_lock_id = l.lock_id

                """

            # 执行版本特定的锁查询
            logger.info(f"执行的 SQL 语句：{lock_sql}")
            lock_result = await execute_sql.run_tool({"query": lock_sql, "tool_name": "get_db_health_running"})
            results.extend(lock_result)
            return results

        except Exception as e:
            logger.error(f"获取锁信息时出错: {str(e)}")
            return [TextContent(type="text", text=f"获取锁信息时出错: {str(e)}")]


########################################################################################################################
class GetDBHealthIndexUsage(BaseHandler):
    name = "get_db_health_index_usage"
    description = (
            "获取当前连接的 MySQL 库的索引使用情况,包含冗余索引情况、性能较差的索引情况、未使用索引且查询时间大于30秒top10情况"
            + "(Get the index usage of the currently connected mysql database, including redundant index situations, "
            + "poorly performing index situations, and the top 10 unused index situations with query times greater than 30 seconds)"
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
        db_manager = get_current_database_manager()
        config = db_manager.get_current_config()

        count_zero_result = await self.get_count_zero(arguments, config)
        max_time_result = await self.get_max_timer(arguments, config)
        not_used_index_result = await self.get_not_used_index(arguments, config)

        # 合并结果
        combined_result = []
        combined_result.extend(count_zero_result)
        combined_result.extend(max_time_result)
        combined_result.extend(not_used_index_result)

        return combined_result

    """
        获取冗余索引情况
    """

    async def get_count_zero(self, arguments: Dict[str, Any], config) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:
            sql = "SELECT object_name,index_name,count_star from performance_schema.table_io_waits_summary_by_index_usage "
            sql += f"WHERE object_schema = '{config['database']}' and count_star = 0 AND sum_timer_wait = 0 ;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_db_health_index_usage"})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取性能较差的索引情况
    """

    async def get_max_timer(self, arguments: Dict[str, Any], config) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:
            sql = "SELECT object_schema,object_name,index_name,(max_timer_wait / 1000000000000) max_timer_wait "
            sql += f"FROM performance_schema.table_io_waits_summary_by_index_usage where object_schema = '{config['database']}' "
            sql += "and index_name is not null ORDER BY  max_timer_wait DESC;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_db_health_index_usage"})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]

    """
        获取未使用索引查询时间大于30秒的top5情况
    """

    async def get_not_used_index(self, arguments: Dict[str, Any], config) -> Sequence[TextContent]:
        execute_sql = ExecuteSQL()

        try:
            sql = "SELECT object_schema,object_name, (max_timer_wait / 1000000000000) max_timer_wait "
            sql += f"FROM performance_schema.table_io_waits_summary_by_index_usage where object_schema = '{config['database']}' "
            sql += "and index_name IS null and max_timer_wait > 30000000000000 ORDER BY max_timer_wait DESC limit 10;"

            logger.info(f"执行的 SQL 语句：{sql}")

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_db_health_index_usage"})
        except Exception as e:
            logger.error(f"执行查询时出错: {str(e)}")
            return [TextContent(type="text", text=f"执行查询时出错: {str(e)}")]


########################################################################################################################
########################################################################################################################
class GetProcessList(BaseHandler):
    name = "get_process_list"
    description = "获取当前进程列表(Get current process list)"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "include_sleeping": {
                        "type": "boolean",
                        "description": "是否包含休眠进程",
                        "default": False
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回的最大结果数量",
                        "default": 20
                    }
                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """获取当前进程列表"""
        execute_sql = ExecuteSQL()

        try:
            include_sleeping = arguments.get("include_sleeping", False)
            max_results = min(arguments.get("max_results", 20), 100)

            sql = """
                SELECT 
                    ID as '进程ID',
                    USER as '用户',
                    HOST as '主机',
                    DB as '数据库',
                    COMMAND as '命令',
                    TIME as '时间(秒)',
                    STATE as '状态',
                    LEFT(INFO, 100) as 'SQL语句'
                FROM information_schema.processlist 
            """

            if not include_sleeping:
                sql += " WHERE COMMAND != 'Sleep'"

            sql += f" ORDER BY TIME DESC LIMIT {max_results}"

            return await execute_sql.run_tool({"query": sql, "tool_name": "get_process_list"})

        except Exception as e:
            logger.error(f"获取进程列表失败: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"获取进程列表失败: {str(e)}")]

########################################################################################################################
