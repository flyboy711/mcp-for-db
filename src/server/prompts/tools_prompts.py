from typing import Dict, Any, Tuple
import re
import datetime
from server.common.prompts import MONITOR_CONFIGS


class MonitoringPromptGenerator:
    """提示词生成器"""

    def __init__(self, user_query: str, parsed_params: Dict[str, Any]):
        """初始化提示词生成器"""
        self.user_query = user_query
        self.parsed_params = self._normalize_params(parsed_params)

    def _normalize_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """标准化参数格式"""
        normalized = {}

        # 确保所有键都是小写
        for key, value in params.items():
            normalized[key.lower()] = value

        # 确保必需参数存在
        normalized.setdefault("monitor_type", "告警")
        normalized.setdefault("time_range", "今天")
        normalized.setdefault("top_k", 10)
        normalized.setdefault("filters", [])

        return normalized

    def generate_prompt(self) -> str:
        """生成宏观编排提示词模板"""
        params = self.parsed_params
        monitor_type = params.get("monitor_type", "告警")
        time_range = params.get("time_range", "今天")
        top_k = params.get("top_k", 10)
        filters = params.get("filters", [])
        sort_by = params.get("sort_by", "")
        group_by = params.get("group_by", "")
        granularity = params.get("granularity", "")

        # 获取监控配置
        config = MONITOR_CONFIGS.get(monitor_type, {})
        if not config:
            config = {
                "primary_table": "相关监控表",
                "core_fields": "时间字段, 实例ID, 指标值",
                "time_field": "时间字段",
                "agg_field": "MAX(指标值) AS peak_value",
                "default_sort": "peak_value DESC",
                "default_viz": "response_table"
            }

        # 计算时间范围
        date_range = self._calculate_date_range(time_range)

        # 获取工具描述
        # tool_descriptions = "\n".join(
        #     f"- {name}: {desc}"
        #     for name, desc in ENHANCED_DESCRIPTIONS.items()
        # )

        # 组装宏观编排提示词
        prompt = f"""
        ## 智能监控查询工作流编排
        **原始查询**: {self.user_query}

        ### 解析参数
        - **监控类型**: {monitor_type}
        - **时间范围**: {time_range} ({date_range[0]} 至 {date_range[1]})
        - **结果数量**: Top{top_k}
        - **筛选条件**: {", ".join(filters) if filters else '无'}
        - **排序规则**: {sort_by if sort_by else config['default_sort']}
        {f"- **分组维度**: {group_by}" if group_by else ""}
        {f"- **时间粒度**: {granularity}" if granularity else ""}

        ### 工作流编排指南
        1. **表发现阶段**:
           - 使用 `get_database_tables`获取数据库的所有表和表注释
           - 使用 `get_table_name` 工具查找主表:
             - 输入描述: "{monitor_type}监控表"
             - 匹配规则: {self._get_table_pattern(monitor_type)}
           - 获取表结构: `get_table_desc` 工具
           {self._get_related_table_instructions(monitor_type)}

        2. **数据准备阶段**:
           - 时间处理: 将"{time_range}"转换为精确的时间范围
           - 字段选择: 核心字段包括 {config['core_fields']}
           {f"- 按{granularity}时间粒度聚合" if granularity else ""}
           {f"- 分组聚合: 使用{config['agg_field']}" if group_by else ""}

        3. **执行阶段**:
           - 使用 `sql_executor` 工具执行最终查询
           - 结果可视化: {config['default_viz']}

        ### 工具调用链建议
        1. 表发现: get_table_name / get_database_tables → get_table_desc
        2. 执行查询: sql_executor

        ### 异常处理
        - **表不存在**: 尝试相近表名匹配
        - **字段缺失**: 使用COALESCE处理空值
        - **权限不足**: 降级为精简查询字段

        ### 输出要求
        - 可视化类型: {config['default_viz']}
        - 时间格式化: `YYYY-MM-DD HH:MI:SS`
        - 返回格式：以 MarkDown 格式返回
        - 安全限制: 最多返回100行

        请根据以上指南编排工具调用链并生成优化SQL!
        """

        return prompt.strip()

    def _calculate_date_range(self, time_range: str) -> Tuple[str, str]:
        """计算时间范围"""
        today = datetime.date.today()
        if time_range == "今天":
            start_date = today
            end_date = today
        elif time_range == "昨天":
            start_date = today - datetime.timedelta(days=1)
            end_date = start_date
        elif time_range == "本周":
            start_date = today - datetime.timedelta(days=today.weekday())
            end_date = today
        elif time_range == "本月":
            start_date = today.replace(day=1)
            end_date = today
        elif "最近" in time_range and "天" in time_range:
            days_match = re.search(r'\d+', time_range)
            if days_match:
                days = int(days_match.group())
                start_date = today - datetime.timedelta(days=days)
                end_date = today
            else:
                start_date = today - datetime.timedelta(days=7)
                end_date = today
        else:
            return "起始时间", "结束时间"

        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    def _get_table_pattern(self, monitor_type: str) -> str:
        """获取表匹配模式"""
        mapping = {
            "告警": r".*alert.*",
            "隐患": "itinerant_main",
            "CPU": r".*perf_cpu.*",
            "内存": r".*perf_mem.*",
            "磁盘": r".*perf_disk.*",
            "网络": r".*perf_network.*"
        }
        return mapping.get(monitor_type, ".*")

    def _get_related_table_instructions(self, monitor_type: str) -> str:
        """获取关联表操作指南"""
        if monitor_type == "隐患":
            return (
                "- 关联隐患定义表: \n"
                "  - 使用 `get_table_name` 工具查找 '隐患定义表' \n"
                "  - 使用 `get_table_desc` 工具获取表结构"
            )
        elif monitor_type in ["CPU", "内存", "磁盘", "网络"]:
            return (
                "- 关联实例信息表: \n"
                "  - 使用 `get_table_name` 工具查找 '实例信息表' \n"
                "  - 使用 `get_table_desc` 工具获取表结构"
            )
        return ""
