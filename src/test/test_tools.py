import asyncio

from pygments.style import ansicolors

from server.config.database import database_manager
from server.tools.mysql.get_table_infos import CheckTableConstraints, GetDatabaseTables, ShowColumnsTool, \
    DescribeTableTool, AnalyzeTableStats, GetTableLock, GetDatabaseInfo, GetTableDesc
from server.tools.mysql.get_table_infos import ShowCreateTableTool

from server.tools.mysql import GetDBHealthRunning, SwitchDatabase


async def main():
    try:
        getDBHealthRunning = GetDBHealthRunning()
        ret = await getDBHealthRunning.run_tool({"table_name": "test_table"})
        print(ret)

        # getTableLock = GetTableLock()
        # ret = await getTableLock.run_tool({"table_name": "test_table"})
        # print(ret)

        # checkTableConstraints = CheckTableConstraints()
        # ret = await checkTableConstraints.run_tool({
        #     "table_name": "timeout_0",
        # })
        # print(ret)

        # getDatabaseTables = GetDatabaseTables()
        # ret = await getDatabaseTables.run_tool({
        #     "include_empty_comments": True,
        # })
        # print(ret)

        # showColumnsTool = ShowColumnsTool()
        # ret = await showColumnsTool.run_tool({
        #     "table": "timeout_0",
        # })
        # print(ret)

        # showCreateTableTool = ShowCreateTableTool()
        # ret = await showCreateTableTool.run_tool({
        #     "table": "timeout_0",
        # })
        # print(ret)

        # describeTableTool = DescribeTableTool()
        # ret = await describeTableTool.run_tool({
        #     "table": "timeout_0",
        # })
        # print(ret)

        # analyzeTableStats = AnalyzeTableStats()
        # ret = await analyzeTableStats.run_tool({
        #     "table_name": "timeout_0",
        # })
        # print(ret)

        # tool = GetDatabaseInfo()
        # ret = await tool.run_tool({"include_connection_info": True})
        # print(ret)

        # tool = GetTableDesc()
        # ret = await tool.run_tool({"text": "timeout_0"})
        # print(ret)


    finally:
        # 使用await调用异步方法
        await database_manager.close_pool()


async def test_switch_db():
    try:
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
            "database": "tpch_tiny",
            "role": "admin"
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
        await database_manager.close_pool()


if __name__ == '__main__':
    # asyncio.run(main())
    asyncio.run(test_switch_db())
