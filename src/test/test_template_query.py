import asyncio
from server.config.request_context import get_current_database_manager
from server.config import SessionConfigManager, DatabaseManager, RequestContext
from server.tools.mysql.use_prompt_query import TemplateQueryExecutor


# 示例用法
async def test_template_query():
    try:
        """测试模板化查询工具"""
        # 创建工具实例
        query_tool = TemplateQueryExecutor()

        # 测试场景1: 获取告警级别最高的前10条告警
        top_alerts = await query_tool.run_tool({
            "query_type": "top_n",
            "table": "t_users",
            "field": "age",
            "order": "DESC",
            "limit": 10
        })
        print("Top 10告警结果:", top_alerts)

        # 测试场景2: 查询今天值班的人员
        today = "2023-10-15"  # 示例日期
        on_duty = await query_tool.run_tool({
            "query_type": "filter_by_value",
            "table": "t_users",
            "field": "created_at",
            "value": today
        })
        print("今天值班人员:", on_duty)

        # 测试场景3: 统计高优先级未解决的告警数量
        # high_priority = await query_tool.run_tool({
        #     "query_type": "aggregate_count",
        #     "table": "alerts",
        #     "condition": "severity = 'HIGH' AND status = 'OPEN'"
        # })
        # print("高优先级未解决告警数量:", high_priority)

        # 测试场景4: 查询过去24小时的告警
        # from datetime import datetime, timedelta
        # end_date = datetime.now().strftime("%Y-%m-%d")
        # start_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        #
        # recent_alerts = await query_tool.run_tool({
        #     "query_type": "date_range",
        #     "table": "alerts",
        #     "date_field": "timestamp",
        #     "start_date": start_date,
        #     "end_date": end_date
        # })
        # print("过去24小时告警:", recent_alerts)

        # 测试场景5: 连接查询告警和关联的事件
        # joined_data = await query_tool.run_tool({
        #     "query_type": "join_tables",
        #     "table1": "alerts",
        #     "table2": "incidents",
        #     "fields": "alerts.id, alerts.severity, incidents.description",
        #     "join_condition": "alerts.incident_id = incidents.id",
        #     "filter_condition": "alerts.severity = 'CRITICAL'"
        # })
        # print("关键告警与事件关联数据:", joined_data)
    finally:
        await get_current_database_manager().close_pool()


if __name__ == "__main__":
    # 创建会话配置管理器
    session_config_1 = SessionConfigManager({
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    })

    # 创建数据库管理器
    db_manager_1 = DatabaseManager(session_config_1)

    # 设置请求上下文
    with RequestContext(session_config_1, db_manager_1):
        asyncio.run(test_template_query())
