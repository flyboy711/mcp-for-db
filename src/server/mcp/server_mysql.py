import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from dotenv import load_dotenv
from starlette.responses import Response
import click
import uvicorn
from pydantic.networks import AnyUrl
from typing import Sequence, Dict, Any, List
from mcp.server.sse import SseServerTransport
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent, Prompt, GetPromptResult, Resource
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.types import Scope, Receive, Send
from server.config import SessionConfigManager
from server.config.database import DatabaseManager
from server.config.dbconfig import EnvFileManager
from server.config.request_context import RequestContext, get_current_database_manager
from server.resources import QueryLogResource
from server.tools.mysql.base import ToolRegistry
from server.prompts.base import PromptRegistry
from server.resources.base import ResourceRegistry
from server.oauth import OAuthMiddleware, login, login_page

# 导入日志配置工具
from server.utils.logger import configure_logger, get_logger
from starlette.middleware import Middleware

# 定义全局资源初始化标识
resources_initialized = False

# 初始化服务器
app = Server("mcp-for-db")
logger = get_logger(__name__)
logger.setLevel(logging.INFO)


async def initialize_global_resources():
    """全局资源初始化函数"""
    global resources_initialized

    if resources_initialized:
        logger.info("资源已初始化，跳过初始化过程")
        return

    logger.info("开始初始化全局资源")
    try:
        # 注意：这里不再初始化全局数据库连接池,每个请求会有自己的数据库管理器

        # 其他全局资源初始化: 比如日志资源、数据库白皮书资源
        QueryLogResource.start_flush_thread()

        logger.info("所有资源初始化完成")
        resources_initialized = True
    except Exception as e:
        logger.exception(f"资源初始化失败:{e}")
        raise


async def close_global_resources():
    """全局资源关闭函数"""
    global resources_initialized

    if not resources_initialized:
        logger.info("资源尚未初始化，无需关闭")
        return

    logger.info("开始关闭所有资源")
    try:
        db = get_current_database_manager()
        await db.close_pool()
        # 关闭其他全局资源
        QueryLogResource.stop_flush_thread()
    except Exception as e:
        logger.exception(f"关闭资源时出错: {str(e)}")
    finally:
        resources_initialized = False


@app.list_resources()
async def handle_get_resources() -> List[Resource]:
    """列出所有可用的 MySQL 表资源"""
    return await ResourceRegistry.get_all_resources()


@app.read_resource()
async def handle_read_resource(uri: AnyUrl) -> str:
    """加载指定资源"""
    try:
        logger.info(f"开始读取资源: {uri}")
        content = await ResourceRegistry.get_resource(uri)
        if content is None:
            content = "null"
        logger.info(f"资源 {uri} 读取成功，内容长度: {len(content)}")
        return content
    except Exception as e:
        logger.error(f"读取资源失败: {str(e)}", exc_info=True)
        raise


@app.list_prompts()
async def handle_list_prompts() -> list[Prompt]:
    """获取所有可用的提示模板列表

    返回:
        list[Prompt]: 返回系统中注册的所有提示模板列表
    """
    logger.info("开始处理获取提示模板列表请求")
    prompts = PromptRegistry.get_all_prompts()
    logger.info(f"成功获取到 {len(prompts)} 个提示模板")
    return prompts


@app.get_prompt()
async def handle_get_prompt(name: str, arguments: Dict[str, Any] | None) -> GetPromptResult:
    """获取并执行指定的提示模板

    参数:
        name (str): 提示模板的名称
        arguments (dict[str, str] | None): 提示模板所需的参数字典，可以为空

    返回:
        GetPromptResult: 提示模板执行的结果

    说明:
        1. 根据提供的模板名称从注册表中获取对应的提示模板
        2. 使用提供的参数执行该模板
        3. 返回执行结果
    """
    logger.info(f"开始处理获取提示模板请求 [name={name}]")
    logger.debug(f"请求参数: {arguments}")

    try:
        prompt = PromptRegistry.get_prompt(name)
        logger.debug(f"找到提示模板 '{name}'")
        result = await prompt.run_prompt(arguments)
        logger.info(f"提示模板 '{name}' 执行成功")
        logger.debug(f"执行结果: {result}")
        return result
    except Exception as e:
        logger.error(f"处理提示模板 '{name}' 时出错: {str(e)}")
        logger.exception("详细错误信息")
        raise


@app.list_tools()
async def list_tools() -> list[Tool]:
    """
        列出所有可用的MySQL操作工具
    """
    logger.info("开始处理获取工具列表请求")
    tools = ToolRegistry.get_all_tools()
    logger.info(f"成功获取到 {len(tools)} 个工具")
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> Sequence[TextContent]:
    """调用指定的工具执行操作

    Args:
        name (str): 工具名称
        arguments (dict): 工具参数

    Returns:
        Sequence[TextContent]: 工具执行结果

    Raises:
        ValueError: 当指定了未知的工具名称时抛出异常
    """
    logger.info(f"开始调用工具 [name={name}]")
    logger.debug(f"工具参数: {arguments}")

    try:
        tool = ToolRegistry.get_tool(name)
        logger.debug(f"找到工具 '{name}'")
        result = await tool.run_tool(arguments)
        logger.info(f"工具 '{name}' 调用成功")
        logger.debug(f"执行结果: {result}")
        return result
    except Exception as e:
        logger.error(f"调用工具 '{name}' 时出错: {str(e)}")
        logger.exception("详细错误信息")
        raise


###############################################################################################
async def run_stdio():
    """运行标准输入输出模式的服务器

    使用标准输入输出流(stdio)运行服务器，主要用于命令行交互模式

    Raises:
        Exception: 当服务器运行出错时抛出异常
    """
    from mcp.server.stdio import stdio_server

    logger.info("启动标准输入输出(stdio)模式服务器")

    try:
        # 初始化资源
        await initialize_global_resources()

        async with stdio_server() as (read_stream, write_stream):
            try:
                logger.debug("初始化流式传输接口")

                # 创建会话配置管理器 - 基于全局默认配置
                session_config = SessionConfigManager(global_default_session_config.get_all())

                # 创建数据库管理器
                db_manager = DatabaseManager(session_config)

                # 设置请求上下文
                with RequestContext(session_config, db_manager):
                    await app.run(
                        read_stream,
                        write_stream,
                        app.create_initialization_options()
                    )

                logger.info("标准输入输出模式服务结束")
            except Exception as e:
                logger.critical(f"标准输入输出模式服务器错误: {str(e)}")
                logger.exception("服务异常终止")
                raise
    finally:
        # 关闭资源
        await close_global_resources()


###############################################################################################
def run_sse():
    """运行SSE(Server-Sent Events)模式的服务器

    启动一个支持SSE的Web服务器，允许客户端通过HTTP长连接接收服务器推送的消息
    服务器默认监听0.0.0.0:9000
    """
    logger.info("启动SSE(Server-Sent Events)模式服务器")
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        """处理SSE连接请求

        Args:
            request: HTTP请求对象
        """
        logger.info(f"新的SSE连接 [client={request.client}]")

        # 创建会话配置管理器 - 基于全局默认配置
        session_config = SessionConfigManager(global_default_session_config.get_all())

        # 创建数据库管理器
        db_manager = DatabaseManager(session_config)

        # 设置请求上下文
        with RequestContext(session_config, db_manager):
            async with sse.connect_sse(
                    request.scope, request.receive, request.send
            ) as streams:
                try:
                    await app.run(streams[0], streams[1], app.create_initialization_options())
                except Exception as e:
                    logger.error(f"SSE连接处理异常: {str(e)}")
                    raise

        logger.info(f"SSE连接断开 [client={request.client}]")
        return Response(status_code=204)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """SSE应用的生命周期管理"""
        try:
            # 初始化资源
            await initialize_global_resources()
            yield
        finally:
            # 关闭资源
            await close_global_resources()

    starlette_app = Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message)
        ],
        lifespan=lifespan
    )

    logger.info("SSE服务器启动中 [host=0.0.0.0, port=9000]")
    # 创建配置并运行
    config = uvicorn.Config(
        app=starlette_app,
        host="0.0.0.0",
        port=9000,
        loop="asyncio",
        log_config=None  # 禁用uvicorn默认日志配置
    )

    server = uvicorn.Server(config)
    server.run()


###############################################################################################
def run_streamable_http(json_response: bool, oauth: bool):
    logger.info("启动Streamable HTTP模式服务器")
    session_manager = StreamableHTTPSessionManager(
        app=app,
        json_response=json_response,
    )

    async def handle_streamable_http(
            scope: Scope, receive: Receive, send: Send
    ) -> None:
        """处理流式HTTP请求"""
        if scope["type"] == "lifespan":
            logger.debug("处理Lifespan协议消息")
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    logger.info("服务器启动完成")
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    logger.info("服务器关闭中...")
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            logger.info(f"新的HTTP请求 [method={scope['method']}, path={scope['path']}, client={scope['client']}]")
            try:
                # 创建会话配置管理器 - 基于全局默认配置
                session_config = SessionConfigManager(global_default_session_config.get_all())

                # 创建数据库管理器
                db_manager = DatabaseManager(session_config)

                # 设置请求上下文
                with RequestContext(session_config, db_manager):
                    await session_manager.handle_request(scope, receive, send)

                logger.info(f"HTTP请求处理完成 [method={scope['method']}, path={scope['path']}]")
            except Exception as e:
                logger.error(f"HTTP请求处理异常: {str(e)}")
                raise

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            """应用生命周期管理"""
            # 初始化资源
            await initialize_global_resources()

            logger.info("服务器初始化...")
            async with session_manager.run():
                logger.info("服务器初始化完成，开始接受请求")
                yield
        finally:
            await close_global_resources()
            logger.info("服务器关闭完成")

    routes = []
    middleware = []
    if oauth:
        middleware.append(
            Middleware(OAuthMiddleware, exclude_paths=["/login", "/mcp/auth/login"])
        )
        routes.append(Route("/login", endpoint=login_page, methods=["GET"]))
        routes.append(Route("/mcp/auth/login", endpoint=login, methods=["POST"]))

    routes.append(Mount("/mcp", app=handle_streamable_http))

    # 创建应用实例
    starlette_app = Starlette(
        debug=True,
        routes=routes,
        middleware=middleware,
        lifespan=lifespan
    )

    config = uvicorn.Config(
        app=starlette_app,
        host="0.0.0.0",
        port=3000,
        lifespan="on",
        log_config=None  # 禁用uvicorn默认日志配置
    )

    server = uvicorn.Server(config)
    logger.info("Streamable HTTP服务器启动中 [host=0.0.0.0, port=3000]")
    server.run()


@click.command()
@click.option("--envfile", default=None, help="env file path")
@click.option("--oauth", default=False, help="open oauth")
@click.option("--mode", default="streamable_http", help="运行模式: sse, stdio, streamable_http")
def main(mode, envfile, oauth):
    """
    主入口函数，用于命令行启动
    支持三种模式：
    1. SSE 模式：mysql-mcp-server
    2. stdio 模式：mysql-mcp-server --stdio
    3. streamable http 模式（默认）

    :param:
        mode (str): 运行模式，可选值为 "sse" 或 "stdio"
        envfile : 自定义环境配置文件
        oauth: 是否启用认证服务
    """

    global global_default_session_config

    # 获取当前文件所在目录的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 获取项目 server 目录
    server_dir = os.path.dirname(current_dir)
    # 获取项目根目录
    root_dir = os.path.dirname(os.path.dirname(server_dir))
    # 配置日志
    configure_logger(log_filename="mcp_server.log")

    logger.info("=" * 60)
    logger.info("开始启动MySQL MCP服务器")

    # 创建全局默认会话配置
    global_default_session_config = SessionConfigManager()

    # 先尝试加载根目录文件中的环境变量是否有新的配置（用户配置的），如果有则获取值更新到默认环境文件中
    env_path_root = os.path.join(root_dir, ".env")
    env_path = os.path.join(server_dir, "config", ".env")
    if os.path.exists(env_path_root):
        # 加载根目录用户配置的环境变量
        load_dotenv(env_path_root)
        logger.info(f"尝试加载根目录中用户配置的环境变量文件: {env_path_root}")
        # 将用户定义的环境变量更新到默认的环境变量文件中
        updates = {
            "MYSQL_HOST": os.environ.get("MYSQL_HOST"),
            "MYSQL_PORT": os.environ.get("MYSQL_PORT"),
            "MYSQL_USER": os.environ.get("MYSQL_USER"),
            "MYSQL_PASSWORD": os.environ.get("MYSQL_PASSWORD"),
            "MYSQL_DATABASE": os.environ.get("MYSQL_DATABASE"),
        }
        EnvFileManager.update(updates, env_path)

        load_dotenv(env_path)
        # 更新全局默认会话配置
        global_default_session_config.update(updates)
        logger.info("用户配置的环境变量已加载到全局默认配置中并更新到默认位置")

    # 再看服务启动时是否指定了env文件
    if envfile:
        logger.info(f"加载服务启动时指定的环境变量文件: {envfile}")
        if os.path.exists(envfile):
            load_dotenv(envfile)
            updates_env = {
                "MYSQL_HOST": os.environ.get("MYSQL_HOST"),
                "MYSQL_PORT": os.environ.get("MYSQL_PORT"),
                "MYSQL_USER": os.environ.get("MYSQL_USER"),
                "MYSQL_PASSWORD": os.environ.get("MYSQL_PASSWORD"),
                "MYSQL_DATABASE": os.environ.get("MYSQL_DATABASE"),
            }
            EnvFileManager.update(updates_env, env_path)
            # 更新全局默认会话配置
            global_default_session_config.update(updates_env)
            logger.info("服务启动时指定的环境变量文件已加载到全局默认配置并更新到默认文件中")
        else:
            logger.warning(f"指定的环境文件不存在: {envfile}")

    # 记录全局默认配置摘要
    logger.info("全局默认配置摘要:")
    for key, value in global_default_session_config.get_all().items():
        if "PASSWORD" in key:
            logger.info(f"{key}: {'*' * 8}")  # 隐藏密码
        else:
            logger.info(f"{key}: {value}")

    # 使用传入的默认模式
    try:
        if mode == "stdio":
            asyncio.run(run_stdio())
        elif mode == "sse":
            run_sse()
        else:
            run_streamable_http(False, oauth)
    except Exception as e:
        logger.critical(f"服务器启动失败: {str(e)}")
        logger.exception("服务器致命错误")
        raise
    finally:
        # 确保资源关闭
        asyncio.run(close_global_resources())
        logger.info("MySQL MCP服务器已关闭")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
