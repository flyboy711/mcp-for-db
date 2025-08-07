import inspect

from mcp_for_db.server.core import BaseMCPServer, ConfigManager
from mcp_for_db.server.server_dify.config import RequestContext, DiFySessionConfig

"""
初始化 DiFyMCPServer 是必须给定该服务的环境配置信息
"""


class DiFyMCPServer(BaseMCPServer):
    """DiFy MCP 服务"""

    def __init__(self, config_manager: ConfigManager):
        super().__init__("dify", config_manager)
        self.global_default_session_config = None

        # 注册表初始化为 None，在 initialize_resources 中创建
        self.tool_registry = None
        self.prompt_registry = None
        self.resource_registry = None

        # 同步初始化
        self._init_managers()

    def _init_managers(self):
        """初始化 DiFy 配置"""
        try:
            self.logger.info("开始初始化DiFy客户端配置")

            self.global_default_session_config = self.config_manager.get_service_config("dify")

            self.logger.info("DiFy客户端配置初始化完成")

        except Exception as e:
            self.logger.error(f"初始化DiFy客户端配置失败: {e}")
            raise

    async def initialize_resources(self):
        """初始化DiFy特有资源（异步方法）"""
        self.logger.info("开始初始化DiFy异步资源...")

        try:
            # 设置注册表（这会触发自动注册）
            await self._setup_registries()
            self.logger.info("DiFy异步资源初始化完成")

        except Exception as e:
            self.logger.error(f"DiFy异步资源初始化失败: {e}")
            raise

    async def _setup_registries(self):
        """设置注册表并触发自动注册"""
        try:
            self.logger.info("开始设置DiFy注册表...")

            # 导入基础注册表类
            from mcp_for_db.server.common.base import ToolRegistry

            # 设置注册表类引用
            self.tool_registry = ToolRegistry

            # 导入所有具体实现模块以触发自动注册
            await self._import_all_modules()

            self.logger.info("DiFy注册表设置完成")

        except Exception as e:
            self.logger.error(f"设置DiFy注册表失败: {e}")
            raise

    async def _import_all_modules(self):
        """导入所有模块以触发自动注册"""
        try:
            self.logger.debug("开始导入DiFy工具、提示词和资源模块...")

            # 导入工具模块（触发工具自动注册）
            try:
                from mcp_for_db.server.server_dify import tools

                # 获取所有导出的工具类并实例化注册
                for tool_name in tools.__all__:
                    try:
                        tool_class = getattr(tools, tool_name)
                        if inspect.isclass(tool_class):
                            # 实例化工具
                            tool_instance = tool_class()

                            # 修复：使用父类的注册方法，假设基类有这个方法
                            if hasattr(self, 'register_tool'):
                                self.register_tool(tool_instance)
                            elif hasattr(tool_instance, 'register'):
                                # 如果工具实例有register方法，调用它
                                tool_instance.register()
                            else:
                                # 如果没有注册方法，至少记录成功创建
                                self.logger.debug(f"工具实例创建成功: {tool_name}")

                            self.logger.debug(f"成功处理工具: {tool_name}")
                    except Exception as e:
                        self.logger.warning(f"处理工具 {tool_name} 失败: {e}")

                self.logger.debug(f"工具模块导入完成，共处理 {len(tools.__all__)} 个工具")

                self.logger.debug("DiFy工具模块导入完成")
            except ImportError as e:
                tools = None
                self.logger.warning(f"某些DiFy工具模块导入失败: {e}")

            self.logger.info("所有DiFy模块导入完成")

        except Exception as e:
            self.logger.error(f"导入DiFy模块时出错: {e}")
            # 不抛出异常，允许部分功能正常工作

    async def create_request_context(self):
        """创建DiFy请求上下文"""
        try:
            # DiFy 不需要复杂的数据库上下文，返回简单的上下文管理器
            session_config = DiFySessionConfig(self.global_default_session_config)
            return RequestContext(session_config)
        except Exception as e:
            self.logger.error(f"创建请求上下文失败: {e}")
            raise

    async def close_resources(self):
        """关闭DiFy特有资源"""
        self.logger.info("开始关闭DiFy资源...")
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

        return []

    def get_resource_registry(self):
        """获取资源注册表"""
        return []
