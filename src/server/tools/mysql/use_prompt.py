from typing import Dict, Any
from mcp import Tool
from mcp.types import TextContent
import logging

from server.tools.mysql.base import BaseHandler
from server.common import VectorCacheManager
from server.prompts.tools_prompts import MonitoringPromptGenerator
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


########################################################################################################################
########################################################################################################################
class DynamicQueryPrompt(BaseHandler):
    """动态提示词编排器 - 使用向量化相似度匹配"""
    name = "dynamic_query_prompt"
    description = "通过动态参数生成提示词模板，支持告警/隐患/性能监控的智能查询服务"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "用户原始查询语句"
                    },
                    "parsed_params": {
                        "type": "object",
                        "description": "大模型解析出的参数",
                        "additionalProperties": True
                    }
                },
                "required": ["user_query"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> TextContent:
        """执行动态提示词编排"""
        user_query = arguments.get("user_query", "")
        parsed_params = arguments.get("parsed_params", {})

        logger.info(f"处理查询: {user_query[:50]}...")
        logger.debug(f"解析参数: {parsed_params}")

        # 1. 检查是否有相似的历史查询
        similar_query = VectorCacheManager.find_similar_query(user_query)

        if similar_query:
            query_hash, cache_data = similar_query
            logger.info(f"缓存命中: {query_hash} (相似度: {cache_data['similarity']:.4f})")
            return TextContent(
                type="text",
                text=cache_data["prompt_text"],
                annotations={
                    "cache_hit": True,
                    "query_hash": query_hash,
                    "similarity": cache_data["similarity"]
                }
            )

        # 2. 使用封装的提示词生成器
        prompt_generator = MonitoringPromptGenerator(user_query, parsed_params)

        # 3. 生成提示词文本
        prompt_text = prompt_generator.generate_prompt()

        # 4. 保存到缓存
        VectorCacheManager.save_params(user_query, parsed_params, prompt_text)

        return TextContent(type="text", text=prompt_text)

########################################################################################################################
########################################################################################################################

########################################################################################################################
########################################################################################################################
