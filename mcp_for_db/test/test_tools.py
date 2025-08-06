import asyncio

from mcp_for_db.server.server_mysql.config import SessionConfigManager, DatabaseManager
from mcp_for_db.server.server_mysql.config.request_context import get_current_database_manager, RequestContext
from mcp_for_db.server.server_mysql.tools import GetDatabaseTables, GetTableDesc, GetDatabaseInfo, GetTableStats, \
    CheckTableConstraints, GetTableLock

from mcp_for_db.server.server_mysql.tools import GetDBHealthRunning, SwitchDatabase, ExecuteSQL, SmartTool, GetTableIndex


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
        ret = await getDatabaseTables.run_tool({})
        print(ret)

        analyzeTableStats = GetTableStats()
        ret = await analyzeTableStats.run_tool({
            "table_name": "t_users",
        })
        print(ret)

        tool = GetDatabaseInfo()
        ret = await tool.run_tool({"include_connection_info": True})
        print(ret)

        tool = GetTableDesc()
        ret = await tool.run_tool({"table_name": "t_users"})
        print(ret)

        tool = GetTableIndex()
        ret = await tool.run_tool({"table_name": "t_users"})
        print(ret)

        tool = GetDatabaseTables()
        ret = await tool.run_tool({"table_name": "t_users"})
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
                "host": "rm-uf6pyrv408i5f0gap.server_mysql.rds.aliyuncs.com",
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
                "parameters": ["25", "26"]
            })

            print(result)

        if num == 2:
            # 使用实例调用 run_tool 方法
            result = await sql_executor.run_tool({
                "query": "SELECT * FROM t_users WHERE age > ? and age<?",
                "parameters": ["25", "27"]
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


async def test_main_use_prompt_tools():
    try:
        ret = SmartTool()

        # print("=== 测试用例1: 基本SQL执行 ===")
        # result = await ret.run_tool({
        #     "user_query": "查询t_users表中年龄25到30岁且姓名以张开头的用户",
        #     "sql_executor.query": "SELECT * FROM t_users WHERE age BETWEEN 25 AND 27 AND name LIKE ?",
        #     "sql_executor.parameters": ["张%"]
        # })
        # print(result)
        # print("\n")

        # print("=== 测试用例2: 带表结构查询的SQL执行 ===")
        # result = await ret.run_tool({
        #     "user_query": "查询用户表的结构并执行查询",
        #     "get_table_desc.table_name": "t_users",
        #     "sql_executor.query": "SELECT * FROM t_users WHERE age > 25 AND age < 27 AND name LIKE ?",
        #     "sql_executor.parameters": ["张%"]
        # })
        # print(result)
        # print("\n")

        print("=== 测试用例3: 多工具协同工作 ===")
        result = await ret.run_tool({
            "user_query": "分析用户查询的性能并优化",
            "get_table_desc.table_name": "t_users",
            "analyze_query_performance.query": "SELECT * FROM t_users WHERE age > 25 AND age < 27",
        })
        print(result)
        print("\n")

        # print("=== 测试用例4: 复杂参数传递 ===")
        # result = await ret.run_tool({
        #     "user_query": "复杂参数传递测试",
        #     "get_table_desc.table_name": "t_users",
        #     "analyze_query_performance.query": "SELECT * FROM t_users",
        #     "collect_table_stats.table_name": "t_users"
        # })
        # print(result)
        # print("\n")

        # print("=== 测试用例5: 带过滤条件的查询 ===")
        # result = await ret.run_tool({
        #     "user_query": "查询活跃用户",
        #     "sql_executor.query": "SELECT * FROM t_users WHERE is_active = ?",
        #     "sql_executor.parameters": [1]
        # })
        # print(result)
        # print("\n")


    finally:
        await get_current_database_manager().close_pool()


async def main2():
    # 创建会话配置管理器
    session_config_1 = SessionConfigManager({
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    })
    # session_config_1 = SessionConfigManager({
    #     "MYSQL_HOST": "rm-uf6pyrv408i5f0gap.server_mysql.rds.aliyuncs.com",
    #     "MYSQL_PORT": "3306",
    #     "MYSQL_USER": "onedba",
    #     "MYSQL_PASSWORD": "S9dKSCsdJm(mKd2",
    #     "MYSQL_DATABASE": "du_trade_timeout_db_3"
    # })

    # 创建数据库管理器
    db_manager_1 = DatabaseManager(session_config_1)

    # 设置请求上下文
    async with RequestContext(session_config_1, db_manager_1):
        await test_main_use_prompt_tools()
        await main_exe_sql(1)
        await main_tools()
        await main_tools_err()
        # await main_switch_db(1)

    # # 创建会话配置管理器
    # session_config_2 = SessionConfigManager({
    #     "MYSQL_HOST": "localhost",
    #     "MYSQL_PORT": "13308",
    #     "MYSQL_USER": "videx",
    #     "MYSQL_PASSWORD": "password",
    #     "MYSQL_DATABASE": "tpch_tiny"
    # })
    #
    # # 创建数据库管理器
    # db_manager_2 = DatabaseManager(session_config_2)
    #
    # # 设置请求上下文
    # async with RequestContext(session_config_2, db_manager_2):
    #     # await main_exe_sql(2)
    #     # await main_tools()
    #     # await main_tools_err()
    #     await main_switch_db(2)


if __name__ == "__main__":
    asyncio.run(main2())
