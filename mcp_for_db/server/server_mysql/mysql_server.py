from mcp_for_db.server.core import BaseMCPServer
from mcp_for_db.server.core import ConfigManager
from mcp_for_db.server.server_mysql.config import DatabaseManager, SessionConfigManager
from mcp_for_db.server.server_mysql.config.request_context import RequestContext
from mcp_for_db.server.common.base import BasePrompt, BaseHandler, BaseResource


class MySQLMCPServer(BaseMCPServer):
    """MySQL MCP服务器实现"""

    def __init__(self, config_manager: ConfigManager):
        super().__init__("mysql", config_manager)
        self.db_manager = None
        self.global_default_session_config = None

        # 注册表初始化为 None，在 initialize_resources 中创建
        self.tool_registry = None
        self.prompt_registry = None
        self.resource_registry = None

        # 初始化管理器
        self._init_managers()

    def _init_managers(self):
        """初始化管理器"""
        try:
            self.logger.info("开始初始化MySQL管理器")
            # 获取全局默认会话配置
            self.global_default_session_config = self.config_manager.get_service_config("mysql")
            self.logger.info("MySQL管理器初始化完成")
        except Exception as e:
            self.logger.error(f"初始化MySQL管理器失败: {e}")
            raise

    async def initialize_resources(self):
        """初始化MySQL特定资源（异步方法）"""
        self.logger.info("开始初始化MySQL异步资源...")

        try:
            # 1. 创建数据库管理器
            session_config = SessionConfigManager(self.global_default_session_config)
            self.db_manager = DatabaseManager(session_config)

            # 2. 初始化数据库连接池
            await self.db_manager.initialize_pool()
            self.logger.info("数据库连接池初始化完成")

            # 3. 创建注册表（此时数据库连接已可用）
            self.tool_registry = BaseHandler()
            self.prompt_registry = BasePrompt()
            self.resource_registry = BaseResource()
            self.logger.info("注册表实例创建完成")

            # 4. 如果注册表需要异步初始化
            if hasattr(self.tool_registry, 'initialize'):
                await self.tool_registry.initialize()
                self.logger.debug("工具注册表异步初始化完成")

            if hasattr(self.prompt_registry, 'initialize'):
                await self.prompt_registry.initialize()
                self.logger.debug("提示词注册表异步初始化完成")

            if hasattr(self.resource_registry, 'initialize'):
                await self.resource_registry.initialize()
                self.logger.debug("资源注册表异步初始化完成")

            self.logger.info("MySQL异步资源初始化完成")

        except Exception as e:
            self.logger.error(f"MySQL异步资源初始化失败: {e}")
            await self._cleanup_partial_resources()
            raise

    async def create_request_context(self):
        """创建请求上下文"""
        try:
            # 为每个请求创建新的会话配置和数据库管理器
            session_config = SessionConfigManager(self.global_default_session_config)
            db_manager = DatabaseManager(session_config)

            # 返回请求上下文
            return RequestContext(session_config, db_manager)
        except Exception as e:
            self.logger.error(f"创建请求上下文失败: {e}")
            raise

    async def _cleanup_partial_resources(self):
        """清理部分初始化的资源"""
        self.logger.info("清理部分初始化的资源...")

        try:
            # 清理注册表
            if hasattr(self.resource_registry, 'close') and self.resource_registry:
                await self.resource_registry.close()
            if hasattr(self.prompt_registry, 'close') and self.prompt_registry:
                await self.prompt_registry.close()
            if hasattr(self.tool_registry, 'close') and self.tool_registry:
                await self.tool_registry.close()

            # 清理数据库管理器
            if self.db_manager:
                await self.db_manager.close_pool()

        except Exception as e:
            self.logger.error(f"清理部分资源时出错: {e}")
        finally:
            # 重置所有引用
            self.tool_registry = None
            self.prompt_registry = None
            self.resource_registry = None
            self.db_manager = None

    async def close_resources(self):
        """关闭MySQL特定资源"""
        self.logger.info("开始关闭MySQL资源...")

        try:
            # 关闭注册表
            if self.resource_registry and hasattr(self.resource_registry, 'close'):
                await self.resource_registry.close()
                self.logger.debug("资源注册表关闭完成")

            if self.prompt_registry and hasattr(self.prompt_registry, 'close'):
                await self.prompt_registry.close()
                self.logger.debug("提示词注册表关闭完成")

            if self.tool_registry and hasattr(self.tool_registry, 'close'):
                await self.tool_registry.close()
                self.logger.debug("工具注册表关闭完成")

            # 关闭数据库管理器
            if self.db_manager:
                await self.db_manager.close_pool()
                self.logger.debug("数据库连接池关闭完成")

        except Exception as e:
            self.logger.error(f"关闭MySQL资源时出错: {e}")
        finally:
            # 重置所有引用
            self.tool_registry = None
            self.prompt_registry = None
            self.resource_registry = None
            self.db_manager = None

        self.logger.info("MySQL资源关闭完成")

    def get_tool_registry(self):
        """获取工具注册表"""
        if self.tool_registry is None:
            self.logger.warning("工具注册表尚未初始化")
        return self.tool_registry

    def get_prompt_registry(self):
        """获取提示词注册表"""
        if self.prompt_registry is None:
            self.logger.warning("提示词注册表尚未初始化")
        return self.prompt_registry

    def get_resource_registry(self):
        """获取资源注册表"""
        if self.resource_registry is None:
            self.logger.warning("资源注册表尚未初始化")
        return self.resource_registry