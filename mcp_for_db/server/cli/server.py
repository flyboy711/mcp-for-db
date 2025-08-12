import asyncio
import contextlib
import click
import signal
from typing import Dict, Any, List, Sequence

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.core import ServiceManager
from mcp_for_db.server.shared.utils import get_logger, configure_logger
from mcp_for_db.server.core.env_distribute import EnvDistributor

logger = get_logger(__name__)
configure_logger("mcp_server_cli.log")
logger.setLevel(LOG_LEVEL)


class AggregatedMCPServer:
    """聚合 MCP 服务：在一个服务中集成多个子服务，因为 stdio 机制是进程间通信，想通过一个项目启动多个服务目前采用聚合方式"""

    def __init__(self, enabled_services):
        self.enabled_services = enabled_services
        self.sub_servers = {}
        self.logger = logger
        self.aggregated_server = None

    ##################################################################################################################
    ##################################################################################################################
    async def initialize_all_services(self):
        """初始化所有启用的子服务"""
        service_manager = ServiceManager()  # 初始化服务管理器时，用户定义的环境变量已经被分发到系统 envs 目录下

        for service_name in self.enabled_services:
            try:
                self.logger.info(f"初始化子服务: {service_name}")
                sub_server = service_manager.create_service(service_name)

                # 执行完整的初始化流程
                await self._initialize_sub_server_complete(sub_server, service_name)

                self.sub_servers[service_name] = sub_server
                logger.info(f"当前子服务的信息: {self.sub_servers[service_name]}")
                self.logger.info(f"子服务 {service_name} 初始化完成")

            except Exception as e:
                self.logger.warning(f"初始化子服务 {service_name} 失败: {e}")
                import traceback
                self.logger.debug(f"详细错误: {traceback.format_exc()}")
                raise

    async def _initialize_sub_server_complete(self, sub_server, service_name):
        """完整初始化子服务: 按照 BaseMCPServer 的标准流程"""
        try:
            # 使用 BaseMCPServer 的标准初始化方法
            if hasattr(sub_server, 'initialize_global_resources'):
                await sub_server.initialize_global_resources()
            else:
                self.logger.warning(f"子服务 {service_name} 没有标准的 initialize_global_resources 方法")
                if hasattr(sub_server, 'initialize_resources'):
                    await sub_server.initialize_resources()

            # 特定服务的额外初始化
            if service_name == "mysql":
                await self._ensure_mysql_initialization(sub_server)
            elif service_name == "dify":
                await self._ensure_dify_initialization(sub_server)

        except Exception as e:
            self.logger.error(f"完整初始化子服务 {service_name} 失败: {e}")
            raise

    async def _ensure_mysql_initialization(self, sub_server):
        """确保 MySQL 服务正确初始化"""
        try:
            await self._initialize_mysql_config(sub_server)
            self.logger.info("MySQL 管理器初始化完成")
        except Exception as e:
            self.logger.error(f"MySQL 管理器初始化失败: {e}")
            raise

    async def _initialize_mysql_config(self, sub_server):
        """初始化 MySQL 管理器"""
        try:
            if not hasattr(sub_server, 'session_config_manager') or sub_server.session_config_manager is None:
                from mcp_for_db.server.server_mysql.config import SessionConfigManager
                sub_server.session_config_manager = SessionConfigManager()
                self.logger.debug("创建 MySQL SessionConfigManager")

            if not hasattr(sub_server, 'database_manager') or sub_server.database_manager is None:
                from mcp_for_db.server.server_mysql.config import DatabaseManager
                sub_server.database_manager = DatabaseManager(sub_server.session_config_manager.server_config)
                self.logger.debug("创建 MySQL DatabaseManager")

        except Exception as e:
            self.logger.error(f"初始化 MySQL 管理器失败: {e}")
            raise

    async def _ensure_dify_initialization(self, sub_server):
        """确保 DiFy 服务正确初始化"""
        try:
            await self._initialize_dify_config(sub_server)
            self.logger.info("DiFy 配置初始化完成")
        except Exception as e:
            self.logger.error(f"DiFy 配置初始化失败: {e}")
            raise

    async def _initialize_dify_config(self, sub_server):
        """初始化 DiFy 配置"""
        try:
            if not hasattr(sub_server, 'session_config') or sub_server.session_config is None:
                from mcp_for_db.server.server_dify.config import DiFySessionConfig
                sub_server.session_config = DiFySessionConfig()
                self.logger.debug("创建 DiFy SessionConfig")

        except Exception as e:
            self.logger.error(f"初始化 DiFy 配置失败: {e}")
            raise

    ##################################################################################################################
    ##################################################################################################################
    async def _create_service_context(self, service_name, sub_server):
        """为特定服务创建正确的请求上下文"""
        try:
            # 根据服务类型创建对应的上下文
            if service_name == "mysql":
                return await self._create_mysql_context(sub_server)

            if service_name == "dify":
                return await self._create_dify_context(sub_server)

        except Exception as e:
            self.logger.error(f"创建服务 {service_name} 的请求上下文失败: {e}")
            raise

    async def _create_mysql_context(self, sub_server):
        """创建 MySQL 服务的专用上下文"""
        try:
            # 确保必要的管理器已初始化
            if not hasattr(sub_server, 'session_config_manager') or sub_server.session_config_manager is None:
                self.logger.warning("MySQL session_config_manager 未初始化，尝试创建...")
                await self._initialize_mysql_config(sub_server)

            if not hasattr(sub_server, 'database_manager') or sub_server.database_manager is None:
                self.logger.warning("MySQL database_manager 未初始化，尝试创建...")
                await self._initialize_mysql_config(sub_server)

            # 检查子服务是否有 create_request_context 方法
            if hasattr(sub_server, 'create_request_context'):
                context = await sub_server.create_request_context()
                self.logger.debug(f"使用子服务的 create_request_context 创建 MySQL 上下文: {type(context)}")
                return context

        except Exception as e:
            self.logger.warning(f"创建 MySQL 上下文失败: {e}")
            import traceback
            self.logger.debug(f"详细错误: {traceback.format_exc()}")
            raise

    async def _create_dify_context(self, sub_server):
        """创建 DiFy 服务的专用上下文"""
        try:
            # 确保会话配置已初始化
            if not hasattr(sub_server, 'session_config') or sub_server.session_config is None:
                self.logger.warning("DiFy session_config 未初始化，尝试创建...")
                await self._initialize_dify_config(sub_server)

            # 检查子服务是否有 create_request_context 方法
            if hasattr(sub_server, 'create_request_context'):
                context = await sub_server.create_request_context()
                self.logger.debug(f"使用子服务的 create_request_context 创建 DiFy 上下文: {type(context)}")
                return context

        except Exception as e:
            self.logger.warning(f"创建 DiFy 上下文失败: {e}")
            import traceback
            self.logger.debug(f"详细错误: {traceback.format_exc()}")
            raise

    ##################################################################################################################
    ##################################################################################################################
    async def create_aggregated_server(self):
        """创建聚合服务器，整合所有子服务的功能"""
        from mcp.server.lowlevel import Server
        from mcp.types import Tool, TextContent, Prompt, GetPromptResult, Resource
        from pydantic.networks import AnyUrl

        # 创建聚合服务器:将多个继承自 BaseMCPServer 的服务视为子服务聚合起来单独提供：受限于公司部署到MCP市场才这么设计
        self.aggregated_server = Server("mcp-aggregated-server")

        # 注册资源处理器
        @self.aggregated_server.list_resources()
        async def handle_list_resources() -> List[Resource]:
            all_resources = []
            for service_name, sub_server in self.sub_servers.items():
                try:
                    # context = await self._create_service_context(service_name, sub_server)
                    # async with context:
                    resource_registry = sub_server.get_resource_registry()
                    if resource_registry and hasattr(resource_registry, 'get_all_resources'):
                        if asyncio.iscoroutinefunction(resource_registry.get_all_resources):
                            resources = await resource_registry.get_all_resources()
                        else:
                            resources = resource_registry.get_all_resources()

                        # 为资源添加服务前缀
                        for resource in resources:
                            original_name = resource.name
                            resource.name = f"{service_name}:{original_name}"
                            # 也更新URI以包含服务前缀
                            if hasattr(resource, 'uri'):
                                resource.uri = f"{service_name}:{resource.uri}"
                        all_resources.extend(resources)

                except Exception as e:
                    self.logger.error(f"获取服务 {service_name} 的资源失败: {e}")
            return all_resources

        @self.aggregated_server.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str:
            uri_str = str(uri)
            if ':' in uri_str:
                service_name, actual_uri = uri_str.split(':', 1)
                if service_name in self.sub_servers:
                    sub_server = self.sub_servers[service_name]
                    # context = await self._create_service_context(service_name, sub_server)
                    # async with context:
                    resource_registry = sub_server.get_resource_registry()
                    if resource_registry and hasattr(resource_registry, 'get_resource'):
                        if asyncio.iscoroutinefunction(resource_registry.get_resource):
                            return await resource_registry.get_resource(AnyUrl(actual_uri))
                        else:
                            return resource_registry.get_resource(AnyUrl(actual_uri))

            raise ValueError(f"未找到资源: {uri}")

        # 注册提示词处理器
        @self.aggregated_server.list_prompts()
        async def handle_list_prompts() -> List[Prompt]:
            all_prompts = []
            for service_name, sub_server in self.sub_servers.items():
                try:
                    # context = await self._create_service_context(service_name, sub_server)
                    # async with context:
                    prompt_registry = sub_server.get_prompt_registry()
                    if prompt_registry and hasattr(prompt_registry, 'get_all_prompts'):
                        if asyncio.iscoroutinefunction(prompt_registry.get_all_prompts):
                            prompts = await prompt_registry.get_all_prompts()
                        else:
                            prompts = prompt_registry.get_all_prompts()

                        # 为提示词添加服务前缀
                        for prompt in prompts:
                            prompt.name = f"{service_name}:{prompt.name}"
                        all_prompts.extend(prompts)

                except Exception as e:
                    self.logger.error(f"获取服务 {service_name} 的提示词失败: {e}")
            return all_prompts

        @self.aggregated_server.get_prompt()
        async def handle_get_prompt(name: str, arguments: Dict[str, Any] | None) -> GetPromptResult:
            if ':' in name:
                service_name, actual_name = name.split(':', 1)
                if service_name in self.sub_servers:
                    sub_server = self.sub_servers[service_name]
                    # context = await self._create_service_context(service_name, sub_server)
                    # async with context:
                    prompt_registry = sub_server.get_prompt_registry()
                    if prompt_registry and hasattr(prompt_registry, 'get_prompt'):
                        if asyncio.iscoroutinefunction(prompt_registry.get_prompt):
                            prompt = await prompt_registry.get_prompt(actual_name)
                        else:
                            prompt = prompt_registry.get_prompt(actual_name)
                        return await prompt.run_prompt(arguments)

            raise ValueError(f"未找到提示词: {name}")

        # 注册工具处理器
        """
        整体架构修改成了微服务式，启动微服务式客户端时一切正常，但在此处聚合的时候，会出现工具重复加载的问题导致工具数翻倍：
        根因在于注册时采用的是全局共享模式自动注册，导致其他服务还会注册一遍，导致翻倍。由于工具不多，此处直接临时过滤去重了
        """

        @self.aggregated_server.list_tools()
        async def list_tools() -> List[Tool]:
            all_tools = []
            registered_tools = set()  # 用于存储已经注册的工具

            # 定义每个服务应该包含的工具
            service_tool_mapping = {
                "mysql": [
                    "sql_executor", "get_query_logs", "switch_database", "collect_table_stats",
                    "get_chinese_initials", "get_table_name", "get_table_desc", "get_table_index",
                    "get_table_lock", "get_database_info", "get_database_tables", "get_table_stats",
                    "check_table_constraints", "get_db_health_running", "get_db_health_index_usage",
                    "get_process_list", "analyze_query_performance", "smart_tool"
                ],
                "dify": [
                    "retrieve_knowledge", "diagnose_knowledge", "switch_dify_knowledge"
                ]
            }

            for service_name, sub_server in self.sub_servers.items():
                try:
                    self.logger.debug(f"获取服务 {service_name} 的工具列表")
                    tool_registry = sub_server.get_tool_registry()

                    if tool_registry is None:
                        self.logger.warning(f"服务 {service_name} 的工具注册表为空")
                        continue

                    if hasattr(tool_registry, 'get_all_tools'):
                        if asyncio.iscoroutinefunction(tool_registry.get_all_tools):
                            tools = await tool_registry.get_all_tools()
                        else:
                            tools = tool_registry.get_all_tools()

                        # 过滤工具：只包含该服务应该有的工具
                        allowed_tools = service_tool_mapping.get(service_name, [])

                        for tool in tools:
                            original_name = tool.name

                            # 只处理该服务应该包含的工具
                            if original_name in allowed_tools:
                                prefixed_name = f"{original_name}"

                                if prefixed_name not in registered_tools:
                                    # 创建新的工具对象，避免修改原对象
                                    from mcp.types import Tool as MCPTool
                                    prefixed_tool = MCPTool(
                                        name=prefixed_name,
                                        description=tool.description,
                                        inputSchema=tool.inputSchema
                                    )
                                    all_tools.append(prefixed_tool)
                                    registered_tools.add(prefixed_name)
                                    self.logger.debug(f"注册工具: {prefixed_name}")
                            else:
                                self.logger.debug(f"跳过工具 {original_name}（不属于服务 {service_name}）")
                    else:
                        self.logger.warning(f"服务 {service_name} 的注册表没有 get_all_tools 方法")

                except Exception as e:
                    self.logger.error(f"获取服务 {service_name} 的工具失败: {e}")
                    import traceback
                    self.logger.debug(f"详细错误: {traceback.format_exc()}")

            self.logger.info(f"总共注册了 {len(all_tools)} 个工具")
            return all_tools

        """
        这里聚合的服务提供的工具直接是原始工具名，供cline这种客户端调用，而自实现的客户端工具格式为：ServerName_ToolName
        """

        @self.aggregated_server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent]:
            self.logger.info(f"调用工具: {name}")
            self.logger.debug(f"工具参数: {arguments}")

            # 解析服务名称和工具名称
            service_name = None
            # 定义每个服务应该包含的工具
            service_tool_mapping = {
                "mysql": [
                    "sql_executor", "get_query_logs", "switch_database", "collect_table_stats",
                    "get_chinese_initials", "get_table_name", "get_table_desc", "get_table_index",
                    "get_table_lock", "get_database_info", "get_database_tables", "get_table_stats",
                    "check_table_constraints", "get_db_health_running", "get_db_health_index_usage",
                    "get_process_list", "analyze_query_performance", "smart_tool"
                ],
                "dify": [
                    "retrieve_knowledge", "diagnose_knowledge", "switch_dify_knowledge"
                ]
            }

            if name in service_tool_mapping.get("mysql", []):
                service_name = "mysql"

            if name in service_tool_mapping.get("dify", []):
                service_name = "dify"

            if service_name in self.sub_servers:
                sub_server = self.sub_servers[service_name]
                try:
                    # 创建服务上下文
                    # context = await self._create_service_context(service_name, sub_server)
                    # async with context:
                    tool_registry = sub_server.get_tool_registry()

                    if tool_registry is None:
                        raise ValueError(f"服务 {service_name} 的工具注册表未初始化")

                    self.logger.debug(f"工具注册表类型: {type(tool_registry)}")

                    if hasattr(tool_registry, 'get_tool'):
                        if asyncio.iscoroutinefunction(tool_registry.get_tool):
                            tool = await tool_registry.get_tool(name)
                        else:
                            tool = tool_registry.get_tool(name)

                        if tool is None:
                            raise ValueError(f"在服务 {service_name} 中未找到工具: {name}")

                        self.logger.debug(f"找到工具: {name}, 类型: {type(tool)}")

                        # 执行工具
                        result = await tool.run_tool(arguments)
                        self.logger.info(f"工具 {name} 执行成功，返回 {len(result) if result else 0} 个结果")
                        return result
                    else:
                        raise ValueError(f"服务 {service_name} 的注册表没有 get_tool 方法")

                except Exception as e:
                    self.logger.error(f"执行工具 {name} 失败: {e}")
                    import traceback
                    self.logger.debug(f"详细错误: {traceback.format_exc()}")
                    # 返回错误信息而不是抛出异常
                    return [TextContent(
                        type="text",
                        text=f"执行工具 {name} 时发生错误: {str(e)}"
                    )]
            else:
                error_msg = f"未找到服务: {service_name}，可用服务: {list(self.sub_servers.keys())}"
                self.logger.error(error_msg)
                return [TextContent(type="text", text=error_msg)]

    ##################################################################################################################
    ##################################################################################################################
    async def run_stdio(self):
        """运行标准输入输出模式的聚合服务器"""
        from mcp.server.stdio import stdio_server

        self.logger.info("启动聚合服务器 stdio 模式")

        try:
            # 初始化所有子服务
            await self.initialize_all_services()

            # 创建聚合服务器
            await self.create_aggregated_server()

            # 为所有子服务创建全局上下文：字典形式：服务名：服务所需上下文
            contexts = {}
            for service_name, sub_server in self.sub_servers.items():
                try:
                    context = await self._create_service_context(service_name, sub_server)
                    contexts[service_name] = context
                    self.logger.info(f"为服务 {service_name} 创建全局上下文成功")
                except Exception as e:
                    self.logger.error(f"为服务 {service_name} 创建全局上下文失败: {e}")
                    contexts[service_name] = None

            # 在所有上下文中运行聚合服务器
            async with self._manage_all_contexts(contexts):
                async with stdio_server() as (read_stream, write_stream):
                    await self.aggregated_server.run(
                        read_stream,
                        write_stream,
                        self.aggregated_server.create_initialization_options()
                    )

        except Exception as e:
            self.logger.error(f"运行聚合服务器失败: {e}")
            raise
        finally:
            await self.cleanup_all_services()

    @contextlib.asynccontextmanager
    async def _manage_all_contexts(self, contexts):
        """管理所有服务的上下文"""
        entered_contexts = []
        try:
            # 进入所有上下文
            for service_name, context in contexts.items():
                if context is not None:
                    try:
                        await context.__aenter__()
                        entered_contexts.append((service_name, context))
                        self.logger.debug(f"服务 {service_name} 上下文已激活")
                    except Exception as e:
                        self.logger.error(f"激活服务 {service_name} 上下文失败: {e}")

            yield

        finally:
            # 退出所有上下文
            for service_name, context in reversed(entered_contexts):
                try:
                    await context.__aexit__(None, None, None)
                    self.logger.debug(f"服务 {service_name} 上下文已关闭")
                except Exception as e:
                    self.logger.error(f"关闭服务 {service_name} 上下文失败: {e}")

    async def cleanup_all_services(self):
        """清理所有子服务"""
        for service_name, sub_server in self.sub_servers.items():
            try:
                self.logger.info(f"清理子服务: {service_name}")
                if hasattr(sub_server, 'close_global_resources'):
                    await sub_server.close_global_resources()
                elif hasattr(sub_server, 'close_resources'):
                    await sub_server.close_resources()
            except Exception as e:
                self.logger.error(f"清理子服务 {service_name} 失败: {e}")

        self.sub_servers.clear()
        self.logger.info("所有子服务清理完成")


@click.command()
@click.option("--mode", type=click.Choice(["stdio", "sse"]), default="stdio", help="传输协议")
@click.option("--services", default="mysql,dify", help="启用的服务列表，逗号分隔")
def main(mode, services):
    """MCP 服务:支持多服务聚合模式"""

    # 解析启用的服务
    enabled_services = [s.strip() for s in services.split(",") if s.strip()]

    async def run_aggregated():
        """运行聚合服务器"""
        try:
            # 初始化环境变量分发器
            logger.info("使用聚合模式启动多个 MCP 服务")
            if mode == "stdio":
                logger.info("stdio 模式启动，开始分发环境变量...")

                # 分发环境变量
                env_distributor = EnvDistributor()
                logger.info(f"验证 {len(enabled_services)} 个启动服务的配置: {enabled_services}")

                if not env_distributor.validate_stdio_config(enabled_services):
                    logger.error("服务配置验证失败")
                    return

                logger.info("所有启动服务配置验证通过")
                env_distributor.distribute_env_vars(enabled_services)

            # 创建聚合服务器
            aggregated_server = AggregatedMCPServer(enabled_services)

            # 根据传输模式运行
            if mode == "stdio":
                await aggregated_server.run_stdio()
            else:
                logger.error(f"聚合模式暂不支持 {mode} 传输协议")

        except Exception as exception:
            logger.error(f"聚合服务器运行错误: {exception}")
            import traceback
            logger.debug(f"详细错误: {traceback.format_exc()}")
            raise

    # 设置信号处理
    def signal_handler(sig, frame):
        logger.info(f"接收到信号 {sig}，正在关闭服务器...")
        raise SystemExit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        asyncio.run(run_aggregated())
    except KeyboardInterrupt:
        logger.info("用户中断，服务器已关闭")
    except Exception as e:
        logger.error(f"服务器运行失败: {e}")
        raise


if __name__ == "__main__":
    main()
