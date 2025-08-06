from mcp_for_db.server.core import BaseMCPServer
from mcp_for_db.server.core import ConfigManager
from mcp_for_db.server.common.base import BasePrompt, BaseHandler, BaseResource


class DiFyMCPServer(BaseMCPServer):
    """DiFy MCP服务"""

    def __init__(self, config_manager: ConfigManager):
        super().__init__("dify", config_manager)

        # 初始化属性
        self.api_base_url = None
        self.api_key = None

        # 注册表初始化为 None，在 initialize_resources 中创建
        self.tool_registry = None
        self.prompt_registry = None
        self.resource_registry = None

        # 同步初始化
        self._init_dify_client()

    def _init_dify_client(self):
        """初始化DiFy客户端配置（同步方法）"""
        try:
            self.logger.info("开始初始化DiFy客户端配置")

            # 修正：使用 config_manager 而不是 config
            dify_config = self.config_manager.get_service_config("dify")

            self.api_base_url = dify_config.get("DIFY_BASE_URL")
            self.api_key = dify_config.get("DIFY_API_KEY")

            if not self.api_base_url:
                raise ValueError("DiFy服务需要配置 API_BASE_URL")
            if not self.api_key:
                raise ValueError("DiFy服务需要配置 API_KEY")

            self.logger.info(f"DiFy API URL: {self.api_base_url}")
            self.logger.info("DiFy客户端配置初始化完成")

        except Exception as e:
            self.logger.error(f"初始化DiFy客户端配置失败: {e}")
            raise

    async def initialize_resources(self):
        """初始化DiFy特有资源（异步方法）"""
        self.logger.info("开始初始化DiFy异步资源...")

        try:
            # 创建注册表
            self.tool_registry = BaseHandler()
            self.prompt_registry = BasePrompt()
            self.resource_registry = BaseResource()
            self.logger.info("DiFy注册表实例创建完成")

        except Exception as e:
            self.logger.error(f"DiFy异步资源初始化失败: {e}")
            # 清理已创建的资源
            await self._cleanup_partial_resources()
            raise

    async def _cleanup_partial_resources(self):
        """清理部分初始化的资源"""
        self.logger.info("清理DiFy部分初始化的资源...")

        try:
            # 清理注册表
            if hasattr(self.tool_registry, 'close') and self.tool_registry:
                await self.tool_registry.close()

        except Exception as e:
            self.logger.error(f"清理DiFy部分资源时出错: {e}")
        finally:
            # 重置所有引用
            self.tool_registry = None
            self.prompt_registry = None
            self.resource_registry = None

    async def close_resources(self):
        """关闭DiFy特有资源"""
        self.logger.info("开始关闭DiFy资源...")

        try:
            # 关闭注册表
            if self.tool_registry and hasattr(self.tool_registry, 'close'):
                await self.tool_registry.close()
                self.logger.debug("工具注册表关闭完成")

        except Exception as e:
            self.logger.error(f"关闭DiFy资源时出错: {e}")
        finally:
            # 重置所有引用
            self.tool_registry = None
            self.prompt_registry = None
            self.resource_registry = None

        self.logger.info("DiFy资源关闭完成")

    def get_tool_registry(self):
        """获取工具注册表"""
        if self.tool_registry is None:
            self.logger.warning("DiFy工具注册表尚未初始化")
        return self.tool_registry

    def get_prompt_registry(self):
        """获取提示词注册表"""
        if self.prompt_registry is None:
            self.logger.warning("DiFy提示词注册表尚未初始化")
        return self.prompt_registry

    def get_resource_registry(self):
        """获取资源注册表"""
        if self.resource_registry is None:
            self.logger.warning("DiFy资源注册表尚未初始化")
        return self.resource_registry

    def create_request_context(self):
        pass
