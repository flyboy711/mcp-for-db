import asyncio
from server.config.database import database_manager
from server.tools.mysql.get_table_infos import CheckTableConstraints, GetDatabaseTables, ShowColumnsTool, \
    DescribeTableTool, AnalyzeTableStats, GetTableLock
from server.tools.mysql.get_table_infos import ShowCreateTableTool


async def main():
    try:
        checkTableConstraints = CheckTableConstraints()
        ret = await checkTableConstraints.run_tool({
            "table_name": "timeout_0",
        })
        print(ret)

        getTableLock = GetTableLock()
        ret = await getTableLock.run_tool({"table_name": "test_table"})
        print(ret)

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

    finally:
        # 使用await调用异步方法
        await database_manager.close_pool()


if __name__ == '__main__':
    asyncio.run(main())
