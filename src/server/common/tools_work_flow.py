from typing import List, Dict, Any

# 自定义工具调用类型
class ToolCall:
    """表示一个工具调用请求"""

    def __init__(self, name: str, arguments: Dict[str, Any]):
        self.name = name
        self.arguments = arguments

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "name": self.name,
            "arguments": self.arguments
        }


class WorkflowOrchestrator:
    """工作流编排器 - 根据参数组装工具调用链"""

    @classmethod
    def generate_workflow(cls, parsed_params: Dict[str, Any]) -> List[ToolCall]:
        """根据解析的参数生成工具调用链"""
        workflow = []

        # 1. 根据监控类型选择主工具
        monitor_type = parsed_params.get("monitor_type", "告警")
        primary_tool = cls._get_primary_tool(monitor_type)
        workflow.append(ToolCall(
            name=primary_tool,
            arguments={"monitor_type": monitor_type}
        ))

        # 2. 添加时间范围处理工具
        time_range = parsed_params.get("time_range", "今天")
        workflow.append(ToolCall(
            name="dynamic_query_prompt",
            arguments={"time_range": time_range}
        ))

        # 3. 添加筛选条件处理工具
        if "filters" in parsed_params and parsed_params["filters"]:
            workflow.append(ToolCall(
                name="dynamic_query_prompt",
                arguments={"filters": parsed_params["filters"]}
            ))

        # 4. 添加排序规则处理工具
        if "sort_by" in parsed_params and parsed_params["sort_by"]:
            workflow.append(ToolCall(
                name="dynamic_query_prompt",
                arguments={"sort_by": parsed_params["sort_by"]}
            ))

        # 5. 添加分组聚合工具
        if "group_by" in parsed_params and parsed_params["group_by"]:
            workflow.append(ToolCall(
                name="dynamic_query_prompt",
                arguments={"group_by": parsed_params["group_by"]}
            ))

        # 6. 添加结果限制工具
        top_k = parsed_params.get("top_k", 10)
        workflow.append(ToolCall(
            name="dynamic_query_prompt",
            arguments={"limit": top_k}
        ))

        return workflow

    @classmethod
    def _get_primary_tool(cls, monitor_type: str) -> str:
        """根据监控类型获取主工具"""
        mapping = {
            "告警": "dynamic_query_prompt",
            "隐患": "dynamic_query_prompt",
            "CPU": "dynamic_query_prompt",
            "内存": "dynamic_query_prompt",
            "磁盘": "dynamic_query_prompt",
            "网络": "dynamic_query_prompt",
            "默认": "sql_executor"
        }
        return mapping.get(monitor_type, mapping["默认"])
