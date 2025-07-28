from typing import List
from server.common import ENHANCED_DESCRIPTIONS
from server.common.tools import SELECTION_RULES


class ToolSelector:
    """工具选择: 提高大模型选择工具的精准度"""

    @classmethod
    def recommend_tools(cls, user_query: str) -> List[str]:
        """根据用户查询推荐最合适的工具"""
        scores = {tool: 0 for tool in ENHANCED_DESCRIPTIONS.keys()}

        # 根据规则加分
        for category, config in SELECTION_RULES.items():
            for keyword in config["keywords"]:
                if keyword.lower() in user_query.lower():
                    for tool in config["tools"]:
                        scores[tool] += 1

        # 根据工具描述加分
        for tool, description in ENHANCED_DESCRIPTIONS.items():
            for keyword in description.split():
                if keyword.lower() in user_query.lower():
                    scores[tool] += 0.5

        # 排序并返回推荐工具
        sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [tool for tool, score in sorted_tools if score > 0]

    @classmethod
    def select_primary_tool(cls, user_query: str, recommended_tools: List[str]) -> str:
        """从推荐工具中选择主工具"""
        # 如果有dynamic_query_prompt且查询符合条件，优先选择
        if "dynamic_query_prompt" in recommended_tools:
            # 检查是否符合监控分析条件
            if any(keyword in user_query for keyword in ["告警", "隐患", "CPU", "内存", "磁盘", "网络"]):
                return "dynamic_query_prompt"

        # 否则返回得分最高的工具
        return recommended_tools[0] if recommended_tools else "sql_executor"
