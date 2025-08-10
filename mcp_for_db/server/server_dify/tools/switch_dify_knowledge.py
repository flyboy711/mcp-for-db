from typing import Dict, Any, Sequence

from mcp import Tool
from mcp.types import TextContent

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.common import ENHANCED_DESCRIPTIONS
from mcp_for_db.server.common.base import BaseHandler
from mcp_for_db.server.server_dify.config import get_current_session_config
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="mcp_tools_dify_knowledge.log")
logger.setLevel(LOG_LEVEL)


class SwitchDiFyKnowledge(BaseHandler):
    name = "switch_dify_knowledge"
    description = ENHANCED_DESCRIPTIONS.get("switch_dify_knowledge")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "base_url": {"type": "string", "description": "DiFy知识库访问基地址"},
                    "api_key": {"type": "string", "description": "DiFy知识库访问的API密钥"},
                    "database_id": {"type": "string", "description": "DiFy知识库ID"}
                },
                "required": ["base_url", "api_key", "database_id"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """切换数据库连接配置"""
        global session_config, current_config
        try:
            # 获取会话配置管理器
            session_config = get_current_session_config()
            if session_config is None:
                return [TextContent(type="text", text="无法获取会话配置管理器")]

            # 保存当前配置（用于回滚）
            current_config = {
                "DIFY_BASE_URL": session_config.get("DIFY_BASE_URL"),
                "DIFY_API_KEY": session_config.get("DIFY_API_KEY"),
                "DIFY_DATASET_ID": session_config.get("DIFY_DATASET_ID"),
            }

            # 准备新配置
            new_config = {
                "DIFY_BASE_URL": arguments["base_url"],
                "DIFY_API_KEY": arguments["api_key"],
                "DIFY_DATASET_ID": arguments["database_id"],
            }

            # 更新会话配置
            session_config.update(new_config)
            logger.info(f"数据库配置已更新: {new_config}")

            return [TextContent(type="text", text="数据库配置已成功切换")]

        except Exception as e:
            logger.error(f"切换数据库失败: {str(e)}")
            session_config.update(current_config)
            logger.info("配置已回滚到之前状态")
            return [TextContent(type="text", text=f"切换数据库失败: {str(e)}")]
