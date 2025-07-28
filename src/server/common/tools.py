########################################################################################################################
# 工具描述增强配置
ENHANCED_DESCRIPTIONS = {
    "smart_tool": (
        "根据用户提问，大模型进行参数解析，然后使用该工具会挑选合适的多个工具协同完成任务"
        "当不知道使用何种工具时，优先使用该工具"
    ),
    "dynamic_query_prompt": (
        "通过动态参数生成提示词模板，主要是为支持告警/隐患/性能监控的智能查询服务，其他查询可不使用该工具"
        "执行复杂的监控数据查询，支持告警、隐患、性能指标的统一查询接口。"
        "使用参数化模板处理时间范围、TopN、分组聚合等复杂查询需求。"
        "适用于包含以下元素的查询："
        "- 时间范围（今天/最近7天/本月）,比如，time_range: '今天' "
        "- top_k 结果，比如，top_k:10/top_k:20"
        "- 告警/隐患/性能指标（CPU/MEM）,比如，monitor_type:'告警' "
        "- 分组聚合（按业务域/负责人分组）,比如，filters: ['业务域=支付']"
        "- 复杂筛选条件（多条件组合）"
    ),
    "get_table_name": (
        "根据表描述或中文名查找对应的物理表名。"
        "当用户使用表描述而非具体表名时使用此工具。"
        "例如：用户提到'用户表'时，查找实际表名如'user_table'。"
    ),
    "get_table_desc": (
        "获取表的详细结构信息，包括字段名、数据类型、约束等。"
        "当需要了解表结构或验证字段存在性时使用此工具。"
    ),
    "get_table_index": (
        "获取表的索引信息，包括索引名称、字段、类型等。"
        "适用于查询优化和索引分析场景。"
    ),
    "get_table_lock": (
        "获取当前MySQL服务器的锁信息，包括行级锁和表级锁。"
        "适用于诊断数据库锁争用问题。"
    ),
    "sql_executor": (
        "执行单条SQL查询语句，支持安全检查和权限控制。"
        "适用于已知表名和字段名的简单查询。"
        "对于复杂查询，建议先使用其他工具获取表结构信息。"
    ),
    "analyze_query_performance": (
        "分析SQL查询的性能特征，包括执行时间、资源使用等。"
        "适用于需要优化查询性能的场景。"
    ),
    "collect_table_stats": (
        "收集表的元数据、统计信息和数据分布情况。"
        "适用于需要了解数据分布特征的场景。"
    ),
    "get_database_info": (
        "获取数据库的基本信息，如版本、字符集、时区等。"
        "适用于数据库状态检查。"
    ),
    "get_database_tables": (
        "获取数据库所有表和对应的表注释。"
        "适用于数据库结构概览。"
    ),
    "get_table_stats": (
        "获取表的统计信息和列统计信息。"
        "适用于查询优化和性能分析。"
    ),
    "check_table_constraints": (
        "检查表的约束信息，包括主键、外键、唯一约束等。"
        "适用于数据库结构验证。"
    ),
    "get_process_list": (
        "获取当前MySQL服务器的进程列表。"
        "适用于诊断数据库性能问题。"
    ),
    "get_db_health_running": (
        "获取当前MySQL的健康状态。"
        "适用于数据库健康检查。"
    ),
    "get_db_health_index_usage": (
        "获取索引使用情况，包括冗余索引、性能较差索引等。"
        "适用于数据库性能优化场景。"
    ),
    "switch_database": (
        "动态切换数据库连接配置。"
        "适用于需要访问不同数据库的场景。"
    ),
    "get_chinese_initials": (
        "将中文字段名转换为拼音首字母字段。"
        "适用于创建表结构时处理中文字段名。"
        "例如：将'用户名'转换为'YHM'。"
    ),
    "get_query_logs": (
        "获取指定工具的历史查询记录，可用于分析工具使用情况和查询模式"
        "适用于开场白提示词：大模型一开始时优先选择该工具"
    )
}
########################################################################################################################
# 工具依赖关系映射
TOOL_DEPENDENCIES = {
    "dynamic_query_prompt": [],
    "get_database_info": [],
    "get_database_tables": [],
    "get_table_name": [],
    "get_table_desc": ["get_table_name", "get_database_tables"],
    "sql_executor": ["get_table_desc", "analyze_query_performance"],
    "analyze_query_performance": ["get_table_desc"],
    "collect_table_stats": ["get_table_desc"],
    "get_db_health_index_usage": ["get_table_index"],
    "get_table_index": ["get_table_desc"],
    "get_table_lock": ["get_table_name"],
    "get_table_stats": ["get_table_desc"],
    "check_table_constraints": ["get_table_desc"],
    "get_process_list": [],
    "get_db_health_running": [],
    "switch_database": [],
    "get_chinese_initials": [],
    "get_query_logs": [],
    "smart_tool": ["get_table_name", "get_database_tables", "get_table_desc", "get_table_stats",
                   "sql_executor", "analyze_query_performance", "dynamic_query_prompt"],
}
########################################################################################################################
# 工具类别映射
TOOL_CATEGORIES = {
    "元数据查询": ["get_table_name", "get_table_desc", "get_table_index", "get_database_info",
                   "get_database_tables"],
    "SQL执行": ["sql_executor", "analyze_query_performance"],
    "监控分析": ["dynamic_query_prompt", "collect_table_stats", "get_table_stats"],
    # "监控分析": ["collect_table_stats", "get_table_stats"],
    "性能诊断": ["get_db_health_index_usage", "get_table_lock", "get_process_list", "get_db_health_running"],
    "辅助工具": ["switch_database", "get_chinese_initials", "get_query_logs", "check_table_constraints",
                 "smart_tool"],
}
########################################################################################################################
########################################################################################################################
# 工具选择规则
SELECTION_RULES = {
    "监控分析": {
        "keywords": ["告警", "隐患", "CPU", "内存", "磁盘", "网络", "监控", "趋势", "分析", "Top", "分组"],
        "tools": ["dynamic_query_prompt", "collect_table_stats", "get_table_stats"]
        # "tools": ["collect_table_stats", "get_table_stats"]
    },

    "表结构查询": {
        "keywords": ["表结构", "字段", "描述", "定义", "元数据"],
        "tools": ["get_table_desc", "get_table_name"]
    },
    "SQL执行": {
        "keywords": ["SELECT", "FROM", "WHERE", "执行SQL", "查询数据"],
        "tools": ["sql_executor"]
    },
    "性能优化": {
        "keywords": ["优化", "性能", "索引", "慢查询", "执行计划"],
        "tools": ["analyze_query_performance", "get_db_health_index_usage"]
    },
    "诊断问题": {
        "keywords": ["锁", "死锁", "阻塞", "进程", "健康状态"],
        "tools": ["get_table_lock", "get_process_list", "get_db_health_running"]
    },
    "辅助操作": {
        "keywords": ["任务编排 智能 检索 查找工具", "切换", "连接", "拼音", "日志", "约束"],
        "tools": ["smart_tool", "switch_database", "get_chinese_initials", "get_query_logs",
                  "check_table_constraints"]
    }
}
