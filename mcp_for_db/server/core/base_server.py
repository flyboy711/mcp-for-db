import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Dict, Any, List, Sequence
import uvicorn
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent, Prompt, GetPromptResult, Resource
from pydantic.networks import AnyUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import Response
from starlette.routing import Route, Mount
from starlette.types import Scope, Receive, Send

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.shared.utils import get_logger, configure_logger
from mcp_for_db.server.core import ConfigManager


class BaseMCPServer(ABC):
    """MCP 多服务基类"""

    def __init__(self, service_name: str, config_manager: ConfigManager):
        self.server = Server(f"mcp-{service_name}")
        self.service_name = service_name
        self.config_manager = config_manager
        self.server_config = config_manager.get_service_config(service_name)
        self.logger = get_logger(f"{service_name}_server")
        self.resources_initialized = False
        self.server_setup_completed = False
        # 设置日志级别
        self.logger.setLevel(LOG_LEVEL)
        configure_logger(log_filename=f"{service_name}_server.log")

    @abstractmethod
    async def initialize_resources(self):
        """初始化服务特定资源"""
        pass

    @abstractmethod
    async def close_resources(self):
        """关闭服务特定资源"""
        pass

    @abstractmethod
    def get_tool_registry(self):
        """获取工具注册表（由子类实现）"""
        pass

    @abstractmethod
    def get_prompt_registry(self):
        """获取提示注册表（由子类实现）"""
        pass

    @abstractmethod
    def get_resource_registry(self):
        """获取资源注册表（由子类实现）"""
        pass

    async def create_request_context(self):
        """创建请求上下文（子类可以重写）"""

        @contextlib.asynccontextmanager
        async def default_context():
            yield

        return default_context()

    async def setup_server(self):
        """设置服务器路由"""
        if self.server_setup_completed:
            self.logger.debug("服务器路由已设置，跳过重复设置")
            return

        self.logger.info("开始设置服务器路由")

        # 注册资源处理器
        @self.server.list_resources()
        async def handle_list_resources() -> List[Resource]:
            try:
                registry = self.get_resource_registry()
                if registry is None:
                    self.logger.warning("资源注册表未初始化，返回空列表")
                    return []

                if hasattr(registry, 'get_all_resources'):
                    if asyncio.iscoroutinefunction(registry.get_all_resources):
                        return await registry.get_all_resources()
                    else:
                        return registry.get_all_resources()
                return []
            except Exception as e:
                self.logger.error(f"获取资源列表失败: {str(e)}", exc_info=True)
                return []

        @self.server.read_resource()
        async def handle_read_resource(uri: AnyUrl) -> str:
            try:
                self.logger.info(f"开始读取资源: {uri}")
                registry = self.get_resource_registry()
                if registry is None:
                    raise ValueError("资源注册表未初始化")

                if hasattr(registry, 'get_resource'):
                    if asyncio.iscoroutinefunction(registry.get_resource):
                        content = await registry.get_resource(uri)
                    else:
                        content = registry.get_resource(uri)
                else:
                    content = None

                if content is None:
                    content = "null"
                self.logger.info(f"资源 {uri} 读取成功，内容长度: {len(content)}")
                return content
            except Exception as e:
                self.logger.error(f"读取资源失败: {str(e)}", exc_info=True)
                raise

        # 注册提示词处理器
        @self.server.list_prompts()
        async def handle_list_prompts() -> List[Prompt]:
            try:
                self.logger.info("开始处理获取提示模板列表请求")
                registry = self.get_prompt_registry()
                if registry is None:
                    self.logger.warning("提示词注册表未初始化，返回空列表")
                    return []

                if hasattr(registry, 'get_all_prompts'):
                    if asyncio.iscoroutinefunction(registry.get_all_prompts):
                        prompts = await registry.get_all_prompts()
                    else:
                        prompts = registry.get_all_prompts()
                else:
                    prompts = []

                self.logger.info(f"成功获取到 {len(prompts)} 个提示模板")
                return prompts
            except Exception as e:
                self.logger.error(f"获取提示词列表失败: {str(e)}", exc_info=True)
                return []

        @self.server.get_prompt()
        async def handle_get_prompt(name: str, arguments: Dict[str, Any] | None) -> GetPromptResult:
            self.logger.info(f"开始处理获取提示模板请求 [name={name}]")
            self.logger.debug(f"请求参数: {arguments}")

            try:
                registry = self.get_prompt_registry()
                if registry is None:
                    raise ValueError("提示词注册表未初始化")

                if hasattr(registry, 'get_prompt'):
                    if asyncio.iscoroutinefunction(registry.get_prompt):
                        prompt = await registry.get_prompt(name)
                    else:
                        prompt = registry.get_prompt(name)
                else:
                    raise ValueError(f"未找到提示模板: {name}")

                self.logger.debug(f"找到提示模板 '{name}'")
                result = await prompt.run_prompt(arguments)
                self.logger.info(f"提示模板 '{name}' 执行成功")
                return result
            except Exception as e:
                self.logger.error(f"处理提示模板 '{name}' 时出错: {str(e)}")
                raise

        # 注册工具处理器
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            try:
                self.logger.info("开始处理获取工具列表请求")
                registry = self.get_tool_registry()
                if registry is None:
                    self.logger.warning("工具注册表未初始化，返回空列表")
                    return []

                if hasattr(registry, 'get_all_tools'):
                    if asyncio.iscoroutinefunction(registry.get_all_tools):
                        tools = await registry.get_all_tools()
                    else:
                        tools = registry.get_all_tools()
                else:
                    tools = []

                self.logger.info(f"成功获取到 {len(tools)} 个工具")
                return tools
            except Exception as e:
                self.logger.error(f"获取工具列表失败: {str(e)}", exc_info=True)
                return []

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent]:
            self.logger.info(f"开始调用工具 [name={name}]")
            self.logger.debug(f"工具参数: {arguments}")

            try:
                registry = self.get_tool_registry()
                if registry is None:
                    raise ValueError("工具注册表未初始化")

                if hasattr(registry, 'get_tool'):
                    if asyncio.iscoroutinefunction(registry.get_tool):
                        tool = await registry.get_tool(name)
                    else:
                        tool = registry.get_tool(name)
                else:
                    raise ValueError(f"未找到工具: {name}")

                self.logger.debug(f"找到工具 '{name}'")
                result = await tool.run_tool(arguments)
                self.logger.info(f"工具 '{name}' 调用成功")
                return result
            except Exception as e:
                self.logger.error(f"调用工具 '{name}' 时出错: {str(e)}")
                raise

        self.server_setup_completed = True
        self.logger.info("服务器路由设置完成")

    async def _initialize_global_resources(self):
        """全局资源初始化"""
        if self.resources_initialized:
            self.logger.info("资源已初始化，跳过初始化过程")
            return

        self.logger.info("开始初始化全局资源")
        try:
            # 1. 首先初始化子类的具体资源
            await self.initialize_resources()

            # 2. 然后设置服务器路由（此时注册表已可用）
            await self.setup_server()

            self.logger.info("所有资源初始化完成")
            self.resources_initialized = True
        except Exception as e:
            self.logger.exception(f"资源初始化失败:{e}")
            raise

    async def _close_global_resources(self):
        """全局资源关闭"""
        if not self.resources_initialized:
            self.logger.info("资源尚未初始化，无需关闭")
            return

        self.logger.info("开始关闭所有资源")
        try:
            await self.close_resources()
        except Exception as e:
            self.logger.exception(f"关闭资源时出错: {str(e)}")
        finally:
            self.resources_initialized = False
            self.server_setup_completed = False

    ####################################################################################################################
    ####################################################################################################################
    async def run_stdio(self):
        """运行标准输入输出模式的服务器"""
        self.logger.info("启动标准输入输出(stdio)模式服务器")

        try:
            await self._initialize_global_resources()

            async with stdio_server() as (read_stream, write_stream):
                try:
                    self.logger.debug("初始化流式传输接口")

                    # 在协议层面创建上下文
                    context = await self.create_request_context()
                    async with context:
                        await self.server.run(
                            read_stream,
                            write_stream,
                            self.server.create_initialization_options()
                        )

                    self.logger.info("标准输入输出模式服务结束")
                except Exception as e:
                    self.logger.critical(f"标准输入输出模式服务器错误: {str(e)}")
                    raise
        finally:
            await self._close_global_resources()
            await asyncio.sleep(0.5)

    def run_sse(self, host: str = "0.0.0.0", port: int = 9000):
        """运行SSE模式的服务器"""
        self.logger.info("启动SSE(Server-Sent Events)模式服务器")
        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            self.logger.info(f"新的SSE连接 [client={request.client}]")

            # 在协议层面创建上下文
            context = await self.create_request_context()
            async with context:
                async with sse.connect_sse(
                        request.scope, request.receive, request._send
                ) as streams:
                    try:
                        await self.server.run(streams[0], streams[1], self.server.create_initialization_options())
                    except Exception as e:
                        self.logger.error(f"SSE连接处理异常: {str(e)}")
                        raise

            self.logger.info(f"SSE连接断开 [client={request.client}]")
            return Response(status_code=204)

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            try:
                await self._initialize_global_resources()
                yield
            finally:
                await self._close_global_resources()
                await asyncio.sleep(0.5)

        starlette_app = Starlette(
            debug=True,
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message)
            ],
            lifespan=lifespan
        )

        self.logger.info(f"SSE服务器启动中 [host={host}, port={port}]")
        config = uvicorn.Config(
            app=starlette_app,
            host=host,
            port=port,
            loop="asyncio",
            log_config=None
        )

        server = uvicorn.Server(config)
        server.run()

    def run_streamable_http(self, host: str = "0.0.0.0", port: int = 3000,
                            json_response: bool = False, oauth: bool = False):
        """运行流式HTTP模式的服务器"""
        self.logger.info("启动Streamable HTTP模式服务器")
        session_manager = StreamableHTTPSessionManager(
            app=self.server,
            json_response=json_response,
        )

        async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                self.logger.debug("处理Lifespan协议消息")
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        self.logger.info("服务器启动完成")
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        self.logger.info("服务器关闭中...")
                        await send({"type": "lifespan.shutdown.complete"})
                        return
            else:
                self.logger.info(f"新的HTTP请求 [method={scope['method']}, path={scope['path']}]")
                try:
                    # 在协议层面创建上下文
                    context = await self.create_request_context()
                    async with context:
                        await session_manager.handle_request(scope, receive, send)

                    self.logger.info(f"HTTP请求处理完成 [method={scope['method']}, path={scope['path']}]")
                except Exception as e:
                    self.logger.error(f"HTTP请求处理异常: {str(e)}")
                    raise

        @contextlib.asynccontextmanager
        async def lifespan(app: Starlette) -> AsyncIterator[None]:
            try:
                await self._initialize_global_resources()
                async with session_manager.run():
                    self.logger.info("服务器初始化完成，开始接受请求")
                    yield
            finally:
                await self._close_global_resources()
                self.logger.info("服务器关闭完成")

        routes = [Mount("/mcp", app=handle_streamable_http)]
        middleware = []

        # 如果需要OAuth
        if oauth:
            try:
                from mcp_for_db.server.shared.oauth import OAuthMiddleware, login, login_page
                middleware.append(
                    Middleware(OAuthMiddleware, exclude_paths=["/login", "/mcp/auth/login"])
                )
                routes.extend([
                    Route("/login", endpoint=login_page, methods=["GET"]),
                    Route("/mcp/auth/login", endpoint=login, methods=["POST"])
                ])
            except ImportError:
                self.logger.warning("OAuth模块未找到，跳过OAuth配置")

        starlette_app = Starlette(
            debug=True,
            routes=routes,
            middleware=middleware,
            lifespan=lifespan
        )

        config = uvicorn.Config(
            app=starlette_app,
            host=host,
            port=port,
            lifespan="on",
            log_config=None
        )

        server = uvicorn.Server(config)
        self.logger.info(f"Streamable HTTP服务器启动中 [host={host}, port={port}]")
        server.run()
