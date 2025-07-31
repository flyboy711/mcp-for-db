import asyncio
import re

from server.tools.mysql import ExecuteSQL, CollectTableStats
from server.config.request_context import get_current_database_manager
from server.config import SessionConfigManager, DatabaseManager, RequestContext


async def parse_slow_log(log_path, threshold=1.0):
    slow_queries = []

    try:
        current_query = {"query": "", "exec_time": 0.0}
        with open(log_path, "r") as f:
            for line in f:
                # 检测新查询的开始（# Time行）
                if line.startswith("# Time:"):
                    # 保存上一个查询（如果满足阈值条件）
                    if current_query["query"] and current_query["exec_time"] >= threshold:
                        slow_queries.append(current_query)
                    # 重置当前查询
                    current_query = {"query": "", "exec_time": 0.0}

                # 提取查询执行时间（关键修复点）
                elif line.startswith("# Query_time:"):
                    match = re.search(r"Query_time:\s*(\d+\.\d+)", line)
                    if match:
                        current_query["exec_time"] = float(match.group(1))

                # 忽略其他元信息行
                elif line.startswith("# User@Host:") or line.startswith("#"):
                    continue

                # 收集SQL查询语句（关键修复点）
                else:
                    # 跳过use和SET语句（可选）
                    if not line.startswith(("use ", "SET timestamp=")):
                        current_query["query"] += line.strip() + " "

            # 处理文件末尾的最后一个查询
            if current_query["query"] and current_query["exec_time"] >= threshold:
                slow_queries.append(current_query)

    except Exception as e:
        print(f"解析慢查询日志时出错: {e}")

    return slow_queries


async def main_tools():
    try:
        db_config = get_current_database_manager().get_current_config()

        execute_sql = ExecuteSQL()
        sql = "SHOW VARIABLES LIKE '%slow_query_log%';"
        result = await execute_sql.run_tool({"query": sql})

        if not result or not result[0].text:
            return ""

        # 获取纯文本内容
        raw_text = result[0].text

        # 标准化处理：去除元数据标记（如果存在）
        if raw_text.startswith('[TextContent(') and raw_text.endswith(')]'):
            # 提取实际内容部分
            content_start = raw_text.find("text='") + 6
            content_end = raw_text.find("',", content_start)
            text_content = raw_text[content_start:content_end]
        else:
            text_content = raw_text

        # 处理换行符：统一转为标准换行符
        normalized_text = text_content.replace('\r\n', '\n').replace('\r', '\n').strip()

        # 按行分割
        lines = normalized_text.split('\n')
        if len(lines) < 2:
            return ""

        # 遍历所有行查找目标值
        slow_query_log_path = ""
        for line in lines:
            # 跳过标题行
            if line.startswith("Variable_name") or not line.strip():
                continue

            # 分割键值对（使用逗号分隔）
            parts = line.split(',', 1)  # 最多分割一次
            if len(parts) < 2:
                continue

            key = parts[0].strip()
            value = parts[1].strip()

            if key == 'slow_query_log_file':
                slow_query_log_path = value
                break

        print(f"Found slow query log path: {slow_query_log_path}")

        result = await parse_slow_log(slow_query_log_path, 0.0)

        print(result)

    finally:
        await get_current_database_manager().close_pool()


async def main():
    try:
        # ret = AnalyzeQueryPerformance()
        ret = CollectTableStats()
        result = await ret.run_tool({
            "table_name": "t_users"
        })

        print(result)
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
    #     "MYSQL_HOST": "rm-uf6pyrv408i5f0gap.mysql.rds.aliyuncs.com",
    #     "MYSQL_PORT": "3306",
    #     "MYSQL_USER": "onedba",
    #     "MYSQL_PASSWORD": "S9dKSCsdJm(mKd2",
    #     "MYSQL_DATABASE": "du_trade_timeout_db_3"
    # })

    # 创建数据库管理器
    db_manager_1 = DatabaseManager(session_config_1)

    # 设置请求上下文
    async with RequestContext(session_config_1, db_manager_1):
        await main()
        # await main_tools()


if __name__ == "__main__":
    asyncio.run(main2())
