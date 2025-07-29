import logging
from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent

from server.common import ENHANCED_DESCRIPTIONS
from server.tools.mysql.base import BaseHandler
from server.utils.logger import get_logger, configure_logger

# 导入上下文获取函数
from server.config.request_context import get_current_session_config, get_current_database_manager

logger = get_logger(__name__)
configure_logger(log_filename="sql_tools.log")
logger.setLevel(logging.WARNING)


async def _reinitialize_db_pool(db_manager) -> None:
    """重新初始化数据库连接池"""
    if hasattr(db_manager, "close_pool") and callable(db_manager.close_pool):
        await db_manager.close_pool()

    if hasattr(db_manager, "initialize_pool") and callable(db_manager.initialize_pool):
        await db_manager.initialize_pool()

    logger.info("数据库连接池已重新初始化")


class SwitchDatabase(BaseHandler):
    name = "switch_database"
    description = ENHANCED_DESCRIPTIONS.get("switch_database")

    # 安全参数设置
    MAX_HOST_LENGTH = 128
    MAX_USER_LENGTH = 64
    MAX_PASSWORD_LENGTH = 128
    MAX_DBNAME_LENGTH = 64

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "数据库主机地址"},
                    "port": {"type": "integer", "description": "数据库端口"},
                    "user": {"type": "string", "description": "数据库用户名"},
                    "password": {"type": "string", "description": "数据库密码"},
                    "database": {"type": "string", "description": "数据库名称"}
                },
                "required": ["host", "port", "user", "password", "database"]
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

            # 获取数据库管理器
            db_manager = get_current_database_manager()
            if db_manager is None:
                return [TextContent(type="text", text="无法获取数据库管理器")]

            # 验证输入参数
            errors = self._validate_input(arguments)
            if errors:
                return [TextContent(type="text", text=f"输入验证失败: {errors}")]

            # 保存当前配置（用于回滚）
            current_config = {
                "MYSQL_HOST": session_config.get("MYSQL_HOST", "localhost"),
                "MYSQL_PORT": session_config.get("MYSQL_PORT", "3306"),
                "MYSQL_USER": session_config.get("MYSQL_USER", ""),
                "MYSQL_PASSWORD": session_config.get("MYSQL_PASSWORD", ""),
                "MYSQL_DATABASE": session_config.get("MYSQL_DATABASE", "")
            }

            # 准备新配置
            new_config = {
                "MYSQL_HOST": arguments["host"],
                "MYSQL_PORT": arguments["port"],
                "MYSQL_USER": arguments["user"],
                "MYSQL_PASSWORD": arguments["password"],
                "MYSQL_DATABASE": arguments["database"]
            }

            # 更新会话配置
            session_config.update(new_config)
            logger.info(f"数据库配置已更新: {new_config}")

            # 重新初始化数据库连接池
            await _reinitialize_db_pool(db_manager)

            return [TextContent(type="text", text="数据库配置已成功切换")]

        except Exception as e:
            logger.error(f"切换数据库失败: {str(e)}")
            session_config.update(current_config)
            logger.info("配置已回滚到之前状态")
            return [TextContent(type="text", text=f"切换数据库失败: {str(e)}")]

    def _validate_input(self, arguments: Dict[str, Any]) -> str:
        """验证输入参数的有效性"""
        errors = []

        # 主机验证
        host = arguments.get("host", "")
        if not host or len(host) > self.MAX_HOST_LENGTH:
            errors.append("主机地址无效")

        # 端口验证
        port = int(arguments.get("port", 0))
        if not isinstance(port, int) or port <= 0 or port > 65535:
            errors.append("端口号无效")

        # 用户验证
        user = arguments.get("user", "")
        if not user or len(user) > self.MAX_USER_LENGTH:
            errors.append("用户名无效")

        # 密码验证
        password = arguments.get("password", "")
        if not password or len(password) > self.MAX_PASSWORD_LENGTH:
            errors.append("密码无效")

        # 数据库名称验证
        database = arguments.get("database", "")
        if not database or len(database) > self.MAX_DBNAME_LENGTH:
            errors.append("数据库名称无效")

        return ", ".join(errors)
