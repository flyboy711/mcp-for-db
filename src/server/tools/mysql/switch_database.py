import logging
from typing import Dict, Any, Sequence
from mcp import Tool
from mcp.types import TextContent

from server.config import MySQLConfigManager, EnvFileManager
from server.tools.mysql.base import BaseHandler
from server.config.database import mysql_pool_manager
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="switch_database.log")


class SwitchDatabase(BaseHandler):
    name = "switch_database"
    description = "动态切换数据库连接配置(Dynamically switch database connection configuration)"

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
                    "database": {"type": "string", "description": "数据库名称"},
                    "role": {"type": "string", "description": "数据库角色（admin/readonly）"}
                },
                "required": ["host", "port", "user", "password", "database", "role"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """切换数据库连接配置

        参数:
            host: 数据库主机地址
            port: 数据库端口
            user: 数据库用户名
            password: 数据库密码
            database: 数据库名称
            role: 数据库角色（admin/readonly）

        返回:
            TextContent: 切换结果信息
        """
        try:
            # 1. 权限验证 - 只有admin角色可以切换数据库
            current_role = MySQLConfigManager().get_config().get("role", "readonly")
            if current_role != "admin":
                return [TextContent(type="text",
                                    text="权限不足: 只有管理员角色可以切换数据库配置")]

            # 2. 验证输入参数
            errors = self._validate_input(arguments)
            if errors:
                return [TextContent(type="text", text=f"输入验证失败: {errors}")]

            # 3. 准备新配置
            new_config = {
                "MYSQL_HOST": arguments["host"],
                "MYSQL_PORT": arguments["port"],
                "MYSQL_USER": arguments["user"],
                "MYSQL_PASSWORD": arguments["password"],
                "MYSQL_DATABASE": arguments["database"],
                "MYSQL_ROLE": arguments["role"]
            }

            # 4. 更新配置
            EnvFileManager.update(new_config)

            # 5. 重新初始化数据库连接池
            await self._reinitialize_db_pool()

            return [TextContent(type="text", text="数据库配置已成功切换")]

        except Exception as e:
            logger.error(f"切换数据库失败: {str(e)}")
            return [TextContent(type="text", text=f"切换数据库失败: {str(e)}")]

    def _validate_input(self, arguments: Dict[str, Any]) -> str:
        """验证输入参数的有效性"""
        errors = []

        # 主机验证
        host = arguments.get("host", "")
        if not host or len(host) > self.MAX_HOST_LENGTH:
            errors.append("主机地址无效")

        # 端口验证
        port = arguments.get("port", 0)
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

        # 角色验证
        role = arguments.get("role", "").lower()
        if role not in ("admin", "readonly"):
            errors.append("角色无效（必须是admin或readonly）")

        return ", ".join(errors)

    @staticmethod
    async def _reinitialize_db_pool(self) -> None:
        """重新初始化数据库连接池"""
        if hasattr(mysql_pool_manager, "close_pool") and callable(mysql_pool_manager.close_pool):
            await mysql_pool_manager.close_pool()

        if hasattr(mysql_pool_manager, "initialize_pool") and callable(mysql_pool_manager.initialize_pool):
            await mysql_pool_manager.initialize_pool()
