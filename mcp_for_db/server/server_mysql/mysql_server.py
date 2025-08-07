import importlib
import inspect
from mcp_for_db.server.core import BaseMCPServer, ConfigManager
from mcp_for_db.server.server_mysql.config import DatabaseManager, SessionConfigManager, RequestContext

"""
初始化 MySQLMCPServer 是必须给定该服务的环境配置信息
"""


class MySQLMCPServer(BaseMCPServer):
    """MySQL MCP 服务器实现"""

    def __init__(self, config_manager: ConfigManager):
        super().__init__("mysql", config_manager)
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
            # 设置注册表（这会触发自动注册）
            await self._setup_registries()

            # 启动全局资源
            await self._start_global_resources()

            self.logger.info("MySQL异步资源初始化完成")

        except Exception as e:
            self.logger.error(f"MySQL异步资源初始化失败: {e}")
            await self._cleanup_partial_resources()
            raise

    async def _setup_registries(self):
        """设置注册表并触发自动注册"""
        try:
            self.logger.info("开始设置MySQL注册表...")

            # 导入基础注册表类
            from mcp_for_db.server.common.base import ToolRegistry, PromptRegistry, ResourceRegistry

            # 设置注册表类引用
            self.tool_registry = ToolRegistry
            self.prompt_registry = PromptRegistry
            self.resource_registry = ResourceRegistry

            # 导入所有具体实现模块以触发自动注册
            await self._import_all_modules()

            self.logger.info("MySQL注册表设置完成")

        except Exception as e:
            self.logger.error(f"设置MySQL注册表失败: {e}")
            raise

    async def _import_all_modules(self):
        """动态导入 - 基于 __init__.py 文件"""
        try:
            self.logger.debug("开始导入MySQL工具、提示词和资源模块...")

            # 1. 导入工具模块 - 直接导入tools包，它会自动导入所有__all__中的工具
            try:
                from mcp_for_db.server.server_mysql import tools

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

            except ImportError as e:
                tools = None
                self.logger.warning(f"工具模块导入失败: {e}")

            # 2. 导入提示词模块 - 动态发现并导入
            try:
                await self._import_prompts_dynamically()
            except Exception as e:
                self.logger.warning(f"提示词模块导入失败: {e}")

            # 3. 导入资源模块 - 动态发现并导入
            try:
                await self._import_resources_dynamically()
            except Exception as e:
                self.logger.warning(f"资源模块导入失败: {e}")

            self.logger.info("所有MySQL模块导入完成")

        except Exception as e:
            self.logger.error(f"导入MySQL模块时出错: {e}")
            # 不抛出异常，允许部分功能正常工作

    async def _import_prompts_dynamically(self):
        """动态导入提示词模块"""
        try:
            # 先尝试导入prompts包
            from mcp_for_db.server.server_mysql import prompts

            # 如果prompts有 __all__，使用它
            if hasattr(prompts, '__all__'):
                for prompt_name in prompts.__all__:
                    try:
                        prompt_obj = getattr(prompts, prompt_name)

                        # 检查对象类型并正确处理
                        if inspect.isclass(prompt_obj):
                            # 如果是类，尝试实例化
                            try:
                                prompt_instance = prompt_obj()
                                self._register_prompt_safe(prompt_instance, prompt_name)
                            except Exception as init_error:
                                self.logger.warning(f"实例化提示词类 {prompt_name} 失败: {init_error}")
                                # 如果实例化失败，尝试直接使用类
                                self._register_prompt_safe(prompt_obj, prompt_name)
                        else:
                            # 如果是实例，直接处理
                            self._register_prompt_safe(prompt_obj, prompt_name)

                    except Exception as e:
                        self.logger.warning(f"处理提示词 {prompt_name} 失败: {e}")
            else:
                # 如果没有__all__，尝试特定导入
                self.logger.warning("prompts 模块未找到，建议统一归整到 __all__ 中")

        except ImportError as e:
            self.logger.warning(f"prompts模块导入失败: {e}")

    async def _import_resources_dynamically(self):
        """动态导入资源模块"""
        try:
            # 先尝试导入resources包
            from mcp_for_db.server.server_mysql import resources

            # 如果resources有__all__，使用它
            if hasattr(resources, '__all__'):
                for resource_name in resources.__all__:
                    try:
                        resource_obj = getattr(resources, resource_name)

                        # 检查对象类型并正确处理
                        if inspect.isclass(resource_obj):
                            # 对于需要参数的资源类，跳过自动实例化
                            if resource_name in ['TableResource', 'QueryLogResource']:
                                self.logger.debug(f"跳过需要参数的资源类: {resource_name}")
                                continue

                            # 尝试无参数实例化
                            try:
                                resource_instance = resource_obj()
                                self._register_resource_safe(resource_instance, resource_name)
                            except Exception as init_error:
                                self.logger.warning(f"实例化资源类 {resource_name} 失败: {init_error}")
                        else:
                            # 如果是实例，直接处理
                            self._register_resource_safe(resource_obj, resource_name)

                    except Exception as e:
                        self.logger.warning(f"处理资源 {resource_name} 失败: {e}")
            else:
                # 如果没有__all__，尝试特定导入
                await self._import_specific_resources()

        except ImportError as e:
            self.logger.warning(f"resources模块导入失败: {e}")

    async def _import_specific_resources(self):
        """导入特定的资源模块"""
        known_resources = [
            'table_resources',
            'query_log_resource'
        ]

        for resource_name in known_resources:
            try:
                resource_module = importlib.import_module(
                    f'mcp_for_db.server.server_mysql.resources.{resource_name}'
                )

                # 从模块中找到资源实例对象（不是类）
                for attr_name in dir(resource_module):
                    if not attr_name.startswith('_'):
                        attr_obj = getattr(resource_module, attr_name)
                        # 检查是否是资源实例（不是类）
                        if (not inspect.isclass(attr_obj) and
                                not inspect.isfunction(attr_obj) and
                                not inspect.ismodule(attr_obj) and
                                (hasattr(attr_obj, 'get_resources') or 'resource' in attr_name.lower())):
                            self._register_resource_safe(attr_obj, attr_name)
                            break

            except ImportError as e:
                self.logger.debug(f"资源模块 {resource_name} 未找到: {e}")

    def _register_prompt_safe(self, prompt_obj, prompt_name):
        """安全注册提示词"""
        try:
            if hasattr(self, 'register_prompt'):
                self.register_prompt(prompt_obj)
            elif hasattr(prompt_obj, 'register'):
                prompt_obj.register()
            else:
                self.logger.debug(f"提示词对象创建成功: {prompt_name}")
            self.logger.debug(f"成功处理提示词: {prompt_name}")
        except Exception as e:
            self.logger.warning(f"注册提示词 {prompt_name} 失败: {e}")

    def _register_resource_safe(self, resource_obj, resource_name):
        """安全注册资源"""
        try:
            if hasattr(self, 'register_resource'):
                self.register_resource(resource_obj)
            elif hasattr(resource_obj, 'register'):
                resource_obj.register()
            else:
                self.logger.debug(f"资源对象创建成功: {resource_name}")
            self.logger.debug(f"成功处理资源: {resource_name}")
        except Exception as e:
            self.logger.warning(f"注册资源 {resource_name} 失败: {e}")

    async def _start_global_resources(self):
        """启动全局资源"""
        try:
            self.logger.debug("启动MySQL全局资源...")

            # 启动查询日志刷新线程等全局资源
            try:
                from mcp_for_db.server.server_mysql.resources.sql_log_resource import QueryLogResource
                if hasattr(QueryLogResource, 'start_flush_thread'):
                    QueryLogResource.start_flush_thread()
                    self.logger.debug("查询日志刷新线程启动完成")
            except ImportError:
                QueryLogResource = None
                self.logger.warning("查询日志资源模块未找到")
            except Exception as e:
                self.logger.warning(f"启动查询日志刷新线程失败: {e}")

            self.logger.info("MySQL全局资源启动完成")

        except Exception as e:
            self.logger.error(f"启动MySQL全局资源失败: {e}")
            raise

    async def create_request_context(self):
        """创建MySQL请求上下文"""
        try:
            # 为每个请求 / 连接创建新的会话配置和数据库管理器
            session_config = SessionConfigManager(self.global_default_session_config)
            db_manager = DatabaseManager(session_config)

            # 返回请求上下文管理器
            return RequestContext(session_config, db_manager)
        except Exception as e:
            self.logger.error(f"创建请求上下文失败: {e}")
            raise

    async def _cleanup_partial_resources(self):
        """清理部分初始化的资源"""
        self.logger.info("清理MySQL部分初始化的资源...")

        try:
            # 清理查询日志资源
            try:
                from mcp_for_db.server.server_mysql.resources.sql_log_resource import QueryLogResource
                if hasattr(QueryLogResource, 'stop_flush_thread'):
                    QueryLogResource.stop_flush_thread()
            except ImportError:
                QueryLogResource = None
                pass
            except Exception as e:
                self.logger.warning(f"停止查询日志刷新线程失败: {e}")

        except Exception as e:
            self.logger.error(f"清理MySQL部分资源时出错: {e}")
        finally:
            # 重置所有引用
            self.tool_registry = None
            self.prompt_registry = None
            self.resource_registry = None

    async def close_resources(self):
        """关闭MySQL特定资源"""
        self.logger.info("开始关闭MySQL资源...")

        try:
            # 关闭查询日志刷新线程等全局资源
            try:
                from mcp_for_db.server.server_mysql.resources.sql_log_resource import QueryLogResource
                if hasattr(QueryLogResource, 'stop_flush_thread'):
                    QueryLogResource.stop_flush_thread()
                    self.logger.debug("查询日志刷新线程关闭完成")
            except ImportError:
                QueryLogResource = None
                pass
            except Exception as e:
                self.logger.warning(f"关闭查询日志刷新线程失败: {e}")

            # 关闭所有数据库连接池（静态方法）
            try:
                from mcp_for_db.server.server_mysql.config.database import DatabaseManager
                await DatabaseManager.close_all_instances()
                self.logger.debug("数据库连接池关闭完成")
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"关闭数据库连接池失败: {e}")

        except Exception as e:
            self.logger.error(f"关闭MySQL资源时出错: {e}")
        finally:
            # 重置所有引用
            self.tool_registry = None
            self.prompt_registry = None
            self.resource_registry = None

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
