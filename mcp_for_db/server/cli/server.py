import asyncio
import click
import signal
import os
from datetime import datetime

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.core import ServiceManager
from mcp_for_db.server.shared.utils import get_logger, configure_logger
from mcp_for_db.server.core.env_distribute import EnvDistributor

logger = get_logger(__name__)
configure_logger("mcp_server_cli.log")
logger.setLevel(LOG_LEVEL)


class AggregatedMCPServer:
    """聚合 MCP 服务器 - 在一个服务中集成多个子服务"""

    def __init__(self, enabled_services):
        self.enabled_services = enabled_services
        self.sub_servers = {}
        self.logger = logger

    async def initialize_all_services(self):
        """初始化所有启用的子服务"""
        service_manager = ServiceManager()

        for service_name in self.enabled_services:
            try:
                self.logger.info(f"初始化子服务: {service_name}")
                sub_server = service_manager.create_service(service_name)

                # 初始化子服务的资源，但不启动stdio
                await sub_server._initialize_global_resources()
                self.sub_servers[service_name] = sub_server

                self.logger.info(f"子服务 {service_name} 初始化完成")
            except Exception as e:
                self.logger.error(f"初始化子服务 {service_name} 失败: {e}")
                raise

    def create_aggregated_server(self):
        """创建聚合的 MCP 服务器"""
        from mcp.server.lowlevel import Server
        from mcp.types import Tool, Prompt, Resource, TextContent, GetPromptResult
        from typing import Dict, Any, List, Sequence
        from pydantic.networks import AnyUrl

        # 创建聚合服务器
        aggregated_server = Server("mcp-aggregated")

        @aggregated_server.list_tools()
        async def list_all_tools() -> List[Tool]:
            """聚合所有子服务的工具"""
            all_tools = []

            for service_name, sub_server in self.sub_servers.items():
                try:
                    tool_registry = sub_server.get_tool_registry()
                    if tool_registry and hasattr(tool_registry, 'get_all_tools'):
                        if asyncio.iscoroutinefunction(tool_registry.get_all_tools):
                            tools = await tool_registry.get_all_tools()
                        else:
                            tools = tool_registry.get_all_tools()

                        # 为工具名称添加服务前缀以避免冲突
                        for tool in tools:
                            tool.name = f"{service_name}_{tool.name}"
                            all_tools.append(tool)

                        self.logger.debug(f"从 {service_name} 获取到 {len(tools)} 个工具")

                except Exception as e:
                    self.logger.warning(f"获取 {service_name} 工具失败: {e}")

            self.logger.info(f"聚合服务器总共提供 {len(all_tools)} 个工具")
            return all_tools

        @aggregated_server.call_tool()
        async def call_aggregated_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent]:
            """调用聚合工具"""
            # 解析服务名称和工具名称
            if '_' in name:
                service_name, tool_name = name.split('_', 1)
            else:
                # 如果没有前缀，尝试在所有服务中查找
                service_name = None
                tool_name = name
                for svc_name, sub_server in self.sub_servers.items():
                    try:
                        tool_registry = sub_server.get_tool_registry()
                        if tool_registry and hasattr(tool_registry, 'get_tool'):
                            if asyncio.iscoroutinefunction(tool_registry.get_tool):
                                tool = await tool_registry.get_tool(tool_name)
                            else:
                                tool = tool_registry.get_tool(tool_name)
                            if tool:
                                service_name = svc_name
                                break
                    except:
                        continue

            if not service_name or service_name not in self.sub_servers:
                raise ValueError(f"找不到工具所属的服务: {name}")

            # 调用对应子服务的工具
            sub_server = self.sub_servers[service_name]
            tool_registry = sub_server.get_tool_registry()

            if asyncio.iscoroutinefunction(tool_registry.get_tool):
                tool = await tool_registry.get_tool(tool_name)
            else:
                tool = tool_registry.get_tool(tool_name)

            self.logger.info(f"调用 {service_name} 服务的工具: {tool_name}")
            return await tool.run_tool(arguments)

        @aggregated_server.list_prompts()
        async def list_all_prompts() -> List[Prompt]:
            """聚合所有子服务的提示词"""
            all_prompts = []

            for service_name, sub_server in self.sub_servers.items():
                try:
                    prompt_registry = sub_server.get_prompt_registry()
                    if prompt_registry and hasattr(prompt_registry, 'get_all_prompts'):
                        if asyncio.iscoroutinefunction(prompt_registry.get_all_prompts):
                            prompts = await prompt_registry.get_all_prompts()
                        else:
                            prompts = prompt_registry.get_all_prompts()

                        # 为提示词名称添加服务前缀
                        for prompt in prompts:
                            prompt.name = f"{service_name}_{prompt.name}"
                            all_prompts.append(prompt)

                        self.logger.debug(f"从 {service_name} 获取到 {len(prompts)} 个提示词")

                except Exception as e:
                    self.logger.warning(f"获取 {service_name} 提示词失败: {e}")

            return all_prompts

        @aggregated_server.get_prompt()
        async def get_aggregated_prompt(name: str, arguments: Dict[str, Any] | None) -> GetPromptResult:
            """获取聚合提示词"""
            # 解析服务名称和提示词名称
            if '_' in name:
                service_name, prompt_name = name.split('_', 1)
            else:
                raise ValueError(f"提示词名称必须包含服务前缀: {name}")

            if service_name not in self.sub_servers:
                raise ValueError(f"找不到提示词所属的服务: {service_name}")

            # 调用对应子服务的提示词
            sub_server = self.sub_servers[service_name]
            prompt_registry = sub_server.get_prompt_registry()

            if asyncio.iscoroutinefunction(prompt_registry.get_prompt):
                prompt = await prompt_registry.get_prompt(prompt_name)
            else:
                prompt = prompt_registry.get_prompt(prompt_name)

            return await prompt.run_prompt(arguments)

        @aggregated_server.list_resources()
        async def list_all_resources() -> List[Resource]:
            """聚合所有子服务的资源"""
            all_resources = []

            for service_name, sub_server in self.sub_servers.items():
                try:
                    resource_registry = sub_server.get_resource_registry()
                    if resource_registry and hasattr(resource_registry, 'get_all_resources'):
                        if asyncio.iscoroutinefunction(resource_registry.get_all_resources):
                            resources = await resource_registry.get_all_resources()
                        else:
                            resources = resource_registry.get_all_resources()

                        all_resources.extend(resources)
                        self.logger.debug(f"从 {service_name} 获取到 {len(resources)} 个资源")

                except Exception as e:
                    self.logger.warning(f"获取 {service_name} 资源失败: {e}")

            return all_resources

        @aggregated_server.read_resource()
        async def read_aggregated_resource(uri: AnyUrl) -> str:
            """读取聚合资源"""
            # 尝试从所有子服务中读取资源
            for service_name, sub_server in self.sub_servers.items():
                try:
                    resource_registry = sub_server.get_resource_registry()
                    if resource_registry and hasattr(resource_registry, 'get_resource'):
                        if asyncio.iscoroutinefunction(resource_registry.get_resource):
                            content = await resource_registry.get_resource(uri)
                        else:
                            content = resource_registry.get_resource(uri)

                        if content is not None:
                            return content

                except Exception as e:
                    self.logger.debug(f"从 {service_name} 读取资源失败: {e}")
                    continue

            raise ValueError(f"找不到资源: {uri}")

        return aggregated_server

    async def run_stdio(self):
        """运行聚合服务器的stdio模式"""
        from mcp.server.stdio import stdio_server

        aggregated_server = self.create_aggregated_server()

        self.logger.info("启动聚合MCP服务器 (stdio模式)")

        try:
            async with stdio_server() as (read_stream, write_stream):
                await aggregated_server.run(
                    read_stream,
                    write_stream,
                    aggregated_server.create_initialization_options()
                )
        finally:
            await self.cleanup_all_services()

    async def cleanup_all_services(self):
        """清理所有子服务"""
        for service_name, sub_server in self.sub_servers.items():
            try:
                await sub_server._close_global_resources()
                self.logger.info(f"子服务 {service_name} 清理完成")
            except Exception as e:
                self.logger.error(f"清理子服务 {service_name} 失败: {e}")


def mcp_server_main(mode, host, server_type, port, oauth):
    """服务启动"""
    service_manager = ServiceManager()

    try:
        service = service_manager.create_service(server_type)

        if mode == "stdio":
            asyncio.run(service.run_stdio())
        elif mode == "sse":
            service.run_sse(host, port)
        elif mode == "streamable_http":
            service.run_streamable_http(host, port, oauth=oauth)

    except Exception:
        raise


@click.command()
@click.option("--mode", default="stdio", type=click.Choice(["stdio", "sse", "streamable_http"]), help="运行模式")
@click.option("--host", default="0.0.0.0", help="主机地址")
@click.option("--mysql_port", type=int, default=3000, help="MySQL服务端口号")
@click.option("--dify_port", type=int, default=3001, help="Dify服务端口号")
@click.option("--oauth", is_flag=False, help="启用OAuth认证")
@click.option("--services", multiple=True, type=click.Choice(["mysql", "dify"]),
              help="要启动的服务，可多选（默认启动所有）")
@click.option("--aggregated", is_flag=True, help="使用聚合模式（stdio下推荐）")
def main(mode, host, mysql_port, dify_port, oauth, services, aggregated):
    # 如果没有指定服务，则启动所有服务
    if not services:
        services = ["mysql", "dify"]

    # stdio模式且启用聚合模式
    if mode == "stdio" and (aggregated or len(services) > 1):
        logger.info("使用聚合模式启动多个MCP服务")
        # 环境变量分发
        logger.info("stdio 模式启动，开始分发环境变量...")
        env_distributor = EnvDistributor()
        validation_result = env_distributor.validate_stdio_config(enabled_services=list(services))

        if not all(validation_result.values()):
            invalid_services = [service for service, valid in validation_result.items() if not valid]
            logger.error(f"以下服务配置无效: {invalid_services}")
            logger.error("请检查环境变量配置后重试")
            raise SystemExit(1)

        logger.info("所有启动服务配置验证通过")
        env_distributor.distribute_env_vars(list(services))

        # 启动聚合服务器
        aggregated_server = AggregatedMCPServer(list(services))

        async def run_aggregated():
            try:
                await aggregated_server.initialize_all_services()
                await aggregated_server.run_stdio()
            except KeyboardInterrupt:
                logger.info("接收到中断信号，正在关闭聚合服务器...")
            except Exception as e:
                logger.error(f"聚合服务器运行错误: {e}")
                raise

        asyncio.run(run_aggregated())
        return

    # 原有的单服务逻辑
    if mode == "stdio":
        if len(services) > 1:
            logger.warning("stdio模式下启动多个服务，建议使用 --aggregated 选项")
            services = [services[0]]  # 只启动第一个服务
            logger.info(f"stdio模式：只启动服务 {services[0]}")

        logger.info(f"{os.environ.get('MYSQL_HOST')}:{os.environ.get('MYSQL_PORT')}")
        logger.info("stdio 模式启动，开始分发环境变量...")

        env_distributor = EnvDistributor()
        validation_result = env_distributor.validate_stdio_config(enabled_services=list(services))

        if not all(validation_result.values()):
            invalid_services = [service for service, valid in validation_result.items() if not valid]
            logger.error(f"以下服务配置无效: {invalid_services}")
            logger.error("请检查环境变量配置后重试")
            raise SystemExit(1)

        logger.info("所有启动服务配置验证通过")
        env_distributor.distribute_env_vars(list(services))

        # 直接运行单个服务
        service_type = services[0]
        port = mysql_port if service_type == "mysql" else dify_port
        logger.info(f"stdio模式启动 {service_type} 服务")
        mcp_server_main(mode, host, service_type, port, oauth)
        return

    # 非stdio模式的多线程逻辑保持不变
    import threading
    import time

    logger.info(f"主参数: mode={mode}, host={host}, mysql_port={mysql_port}, dify_port={dify_port}, oauth={oauth}")

    threads = []
    stop_event = threading.Event()

    # 启动MySQL服务的线程
    if "mysql" in services:
        def mysql_thread_func():
            try:
                logger.info(f"启动MySQL服务 (线程ID: {threading.get_ident()})")
                mcp_server_main(mode, host, "mysql", mysql_port, oauth)
            except Exception as exception:
                logger.exception(f"MySQL服务异常: {exception}")
            finally:
                logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] MySQL服务已停止")

        mysql_thread = threading.Thread(target=mysql_thread_func, name="MySQL_Service")
        mysql_thread.daemon = True
        mysql_thread.start()
        threads.append(("MySQL", mysql_thread))
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] MySQL服务已启动 (线程ID: {mysql_thread.ident})")

    # 启动Dify服务的线程
    if "dify" in services:
        def dify_thread_func():
            try:
                logger.info(f"启动Dify服务 (线程ID: {threading.get_ident()})")
                mcp_server_main(mode, host, "dify", dify_port, oauth)
            except Exception as exception:
                logger.exception(f"Dify服务异常: {exception}")
            finally:
                logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Dify服务已停止")

        dify_thread = threading.Thread(target=dify_thread_func, name="Dify_Service")
        dify_thread.daemon = True
        dify_thread.start()
        threads.append(("Dify", dify_thread))
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Dify服务已启动 (线程ID: {dify_thread.ident})")

    if not threads:
        logger.info("未启动任何服务")
        return

    logger.info(f"已启动 {len(threads)} 个服务，模式: {mode}")
    logger.info("按 Ctrl+C 停止所有服务")

    # 信号处理和线程监控逻辑保持不变
    def signal_handler(signum, frame):
        logger.info("\n收到中断信号，正在关闭服务...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while not stop_event.is_set():
            time.sleep(1)
            running_count = sum(1 for _, thread in threads if thread.is_alive())
            if running_count == 0:
                logger.info("所有服务已停止")
                break
        else:
            for service_name, thread in threads:
                thread.join(timeout=5)
                if thread.is_alive():
                    logger.warning(f"{service_name} 服务线程未能在超时内停止")

    except Exception as e:
        logger.exception(f"服务监控异常: {e}")
    finally:
        logger.info("服务控制器退出")
        stop_event.set()


if __name__ == '__main__':
    main()