# 工具描述增强配置
import os
from pathlib import Path

ENHANCED_DESCRIPTIONS = {
    "dynamic_query_prompt": (
        "通过动态参数生成提示词模板，主要是为支持告警/隐患/性能监控的智能查询服务，其他查询可不使用该工具"
        "执行复杂的监控数据查询，支持告警、隐患、性能指标的统一查询接口。"
        "使用参数化模板处理时间范围、TopN、分组聚合等复杂查询需求。"
        "适用于包含以下元素的查询："
        "- 时间范围（今天/最近7天/本月）"
        "- TopN结果（Top10/Top20）"
        "- 告警/隐患/性能指标（CPU/MEM）"
        "- 分组聚合（按业务域/负责人分组）"
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

if __name__ == "__main__":
    CACHE_DIR = Path(__file__).parent.parent.parent.parent / "files/vector_cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print(CACHE_DIR)
