from typing import Dict, Sequence, Any
from mcp import Tool
from mcp.types import TextContent
from server.tools.mysql import ExecuteSQL
import logging
from server.tools.mysql.base import BaseHandler

logger = logging.getLogger(__name__)


class UsePromptQueryTableData(BaseHandler):
    name = "use_prompt_queryTableData"
    description = (
        "查询表名，表字段，随后执行查询工具，（Retrieve data records from the database table.）"
    )

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {

                }
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        prompt = f"""
                - Workflow:
                  1. 解析用户输入的自然语言指令，提取关键信息，如表描述和查询条件。
                  2. 判断是否跨库查询、是否明确指定了目标表名（例如是中文的描述、英文的描述，偏向语义化的描述则判断为未明确表名）
                  3. 未明确指定目标表名则调用“get_table_name”工具，获取对应的表名。
                  4. 调用“get_table_desc”工具，获取表的结构信息。
                  5. 根据表结构信息和用户输入的查询条件，生成SQL查询语句并调用“execute_sql”工具，返回查询结果。
                - Examples:
                  - 例子1：用户输入“查询用户表张三的数据”
                    解析结果：表描述为“用户表”，查询条件为“张三”。
                    判断结果：1.没有出现跨库的情况 2.未明确指定表名，当前为表的描述，需调用工具获取表名
                    调用工具“get_table_name”：根据“用户表”描述获取表名，假设返回表名为“user_table”。
                    调用工具“get_table_desc”：根据“user_table”获取表结构，假设表结构包含字段“id”、“name”、“age”。
                    生成SQL查询语句：`SELECT * FROM user_table WHERE name = '张三';`
                    调用工具“execute_sql”：根据生成的SQL,获取结果。
                    查询结果：返回张三的相关数据。
                - task: 
                  - 调用工具“get_table_name”，
                  - 调用工具“get_table_desc”，
                  - 调用工具“execute_sql”
                  - 以markdown格式返回执行结果
                """

        return [TextContent(type="text", text=prompt)]


########################################################################################################################
class TemplateQueryExecutor(BaseHandler):
    """模板化查询执行器，支持多种常见查询模式"""
    name = "template_query_executor"
    description = (
        "执行模板化查询任务，支持Top N查询、特定条件查询、聚合查询等常见模式。"
        "通过参数化模板实现通用查询功能。"
    )

    # 预定义查询模板
    QUERY_TEMPLATES = {
        "top_n": {
            "description": "获取表中指定字段的Top N记录",
            "template": "SELECT * FROM {table} ORDER BY {field} {order} LIMIT {limit}"
        },
        "filter_by_value": {
            "description": "根据字段值过滤记录",
            "template": "SELECT * FROM {table} WHERE {field} = '{value}'"
        },
        "filter_by_condition": {
            "description": "根据条件表达式过滤记录",
            "template": "SELECT * FROM {table} WHERE {condition}"
        },
        "aggregate_count": {
            "description": "统计满足条件的记录数量",
            "template": "SELECT COUNT(*) AS count FROM {table} WHERE {condition}"
        },
        "date_range": {
            "description": "查询指定日期范围内的记录",
            "template": "SELECT * FROM {table} WHERE {date_field} BETWEEN '{start_date}' AND '{end_date}'"
        },
        "join_tables": {
            "description": "连接多个表查询",
            "template": "SELECT {fields} FROM {table1} JOIN {table2} ON {join_condition} WHERE {filter_condition}"
        }
    }

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "query_type": {
                        "type": "string",
                        "description": "查询类型",
                        "enum": list(self.QUERY_TEMPLATES.keys()),
                        "default": "top_n"
                    },
                    "table": {
                        "type": "string",
                        "description": "目标表名"
                    },
                    "field": {
                        "type": "string",
                        "description": "目标字段名"
                    },
                    "value": {
                        "type": "string",
                        "description": "字段值"
                    },
                    "condition": {
                        "type": "string",
                        "description": "查询条件表达式"
                    },
                    "order": {
                        "type": "string",
                        "description": "排序方式",
                        "enum": ["ASC", "DESC"],
                        "default": "DESC"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回记录数限制",
                        "default": 10
                    },
                    "date_field": {
                        "type": "string",
                        "description": "日期字段名"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "开始日期 (YYYY-MM-DD)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期 (YYYY-MM-DD)"
                    },
                    "fields": {
                        "type": "string",
                        "description": "需要返回的字段列表 (逗号分隔)"
                    },
                    "table1": {
                        "type": "string",
                        "description": "主表名 (用于连接查询)"
                    },
                    "table2": {
                        "type": "string",
                        "description": "连接表名 (用于连接查询)"
                    },
                    "join_condition": {
                        "type": "string",
                        "description": "表连接条件"
                    },
                    "filter_condition": {
                        "type": "string",
                        "description": "过滤条件"
                    }
                },
                "required": ["query_type", "table"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行模板化查询"""
        query_type = arguments.get("query_type", "top_n")

        # 获取查询模板
        template_info = self.QUERY_TEMPLATES.get(query_type)
        if not template_info:
            return [TextContent(
                text=f"未知查询类型: {query_type}",
                annotations={"error": "invalid_query_type"}
            )]

        # 渲染SQL模板
        try:
            sql_query = self._render_template(template_info["template"], arguments)
            logger.info(f"生成的SQL查询: {sql_query}")
        except KeyError as e:
            return [TextContent(
                text=f"缺少必要参数: {str(e)}",
                annotations={"error": "missing_parameter"}
            )]

        # 创建SQL执行工具实例
        execute_sql = ExecuteSQL()

        # 执行查询
        try:
            result = await execute_sql.run_tool({"query": sql_query})
            return result
        except Exception as e:
            logger.error(f"执行查询失败: {str(e)}")
            return [TextContent(
                text=f"查询执行失败: {str(e)}",
                annotations={"error": "query_execution_failed"}
            )]

    def _render_template(self, template: str, arguments: Dict[str, Any]) -> str:
        """渲染SQL模板"""
        # 处理特殊参数
        if "fields" in arguments and isinstance(arguments["fields"], list):
            arguments["fields"] = ", ".join(arguments["fields"])

        # 渲染模板
        return template.format(**arguments)
