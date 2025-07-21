import asyncio

from server.config import SessionConfigManager, DatabaseManager
from server.config.request_context import get_current_database_manager, RequestContext
from server.tools.mysql.get_table_infos import GetDatabaseTables, GetTableDesc, GetDatabaseInfo, AnalyzeTableStats, \
    CheckTableConstraints, GetTableLock

from server.tools.mysql import GetDBHealthRunning, SwitchDatabase, ExecuteSQL


async def main_tools():
    db_manager = get_current_database_manager()
    try:
        getDBHealthRunning = GetDBHealthRunning()
        ret = await getDBHealthRunning.run_tool({"table_name": "test_table"})
        print(ret)

        checkTableConstraints = CheckTableConstraints()
        ret = await checkTableConstraints.run_tool({
            "table_name": "t_users",
        })
        print(ret)

        getDatabaseTables = GetDatabaseTables()
        ret = await getDatabaseTables.run_tool({
            "include_empty_comments": True,
        })
        print(ret)

        analyzeTableStats = AnalyzeTableStats()
        ret = await analyzeTableStats.run_tool({
            "table_name": "t_users",
        })
        print(ret)

        tool = GetDatabaseInfo()
        ret = await tool.run_tool({"include_connection_info": True})
        print(ret)

        tool = GetTableDesc()
        ret = await tool.run_tool({"text": "t_users"})
        print(ret)


    finally:
        # 使用await调用异步方法
        await db_manager.close_pool()


async def main_switch_db(num: int = 1):
    try:
        if num == 1:
            getDatabaseTables = GetDatabaseTables()
            ret = await getDatabaseTables.run_tool({
                "include_empty_comments": True,
            })
            print(ret)

            tool = SwitchDatabase()
            arguments = {
                "host": "localhost",
                "port": "13308",
                "user": "videx",
                "password": "password",
                "database": "tpch_tiny"
            }
            result = await tool.run_tool(arguments)

            print(result)

            getDatabaseTables = GetDatabaseTables()
            ret = await getDatabaseTables.run_tool({
                "include_empty_comments": True,
            })
            print(ret)

        if num == 2:
            getDatabaseTables = GetDatabaseTables()
            ret = await getDatabaseTables.run_tool({
                "include_empty_comments": True,
            })
            print(ret)

            tool = SwitchDatabase()
            arguments = {
                "host": "rm-uf6pyrv408i5f0gap.mysql.rds.aliyuncs.com",
                "port": "3306",
                "user": "onedba",
                "password": "S9dKSCsdJm(mKd2",
                "database": "du_trade_timeout_db_3",
            }
            result = await tool.run_tool(arguments)

            print(result)

            getDatabaseTables = GetDatabaseTables()
            ret = await getDatabaseTables.run_tool({
                "include_empty_comments": True,
            })
            print(ret)
    finally:
        # 使用await调用异步方法
        await get_current_database_manager().close_pool()


async def main_exe_sql(num: int = 1):
    sql_executor = ExecuteSQL()
    try:
        if num == 1:
            # 使用实例调用 run_tool 方法
            result = await sql_executor.run_tool({
                "query": "SELECT * FROM t_users WHERE age > ? and age<?",
                "parameters": ["25", "30"]
            })

            print(result)

        if num == 2:
            # 使用实例调用 run_tool 方法
            result = await sql_executor.run_tool({
                "query": "SELECT * FROM t_users WHERE age > ? and age<?",
                "parameters": ["25", "26"]
            })

            print(result)
    finally:
        await get_current_database_manager().close_pool()


async def main_tools_err():
    try:
        getTableLock = GetTableLock()
        ret = await getTableLock.run_tool({"table_name": "t_users"})
        print(ret)
    finally:
        await get_current_database_manager().close_pool()


if __name__ == "__main__":
    # 创建会话配置管理器
    # session_config_1 = SessionConfigManager({
    #     "MYSQL_HOST": "localhost",
    #     "MYSQL_PORT": "13308",
    #     "MYSQL_USER": "videx",
    #     "MYSQL_PASSWORD": "password",
    #     "MYSQL_DATABASE": "tpch_tiny"
    # })
    # session_config_1 = SessionConfigManager({
    #     "MYSQL_HOST": "rm-uf6pyrv408i5f0gap.mysql.rds.aliyuncs.com",
    #     "MYSQL_PORT": "3306",
    #     "MYSQL_USER": "onedba",
    #     "MYSQL_PASSWORD": "S9dKSCsdJm(mKd2",
    #     "MYSQL_DATABASE": "du_trade_timeout_db_3"
    # })
    #
    # # 创建数据库管理器
    # db_manager_1 = DatabaseManager(session_config_1)
    #
    # # 设置请求上下文
    # with RequestContext(session_config_1, db_manager_1):
    #     asyncio.run(main_exe_sql(1))
    #     # asyncio.run(main_tools())
    #     # asyncio.run(main_tools_err())
    #     # asyncio.run(main_switch_db(1))

    # 创建会话配置管理器
    session_config_2 = SessionConfigManager({
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    })

    # 创建数据库管理器
    db_manager_2 = DatabaseManager(session_config_2)

    # 设置请求上下文
    with RequestContext(session_config_2, db_manager_2):
        # asyncio.run(main_exe_sql(2))
        # asyncio.run(main_tools())
        # asyncio.run(main_switch_db(2))
        asyncio.run(main_tools_err())
