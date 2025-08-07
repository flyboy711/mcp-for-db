import asyncio
import click
from mcp_for_db.server.core import ServiceManager


@click.command()
@click.option("--mode", default="stdio", type=click.Choice(["stdio", "sse", "streamable_http"]), help="运行模式")
@click.option("--host", default="0.0.0.0", help="主机地址")
@click.option("--port", type=int, help="端口号")
def main(mode, host, port):
    """DiFy MCP服务启动器"""

    service_manager = ServiceManager()

    try:
        service = service_manager.create_service("dify")

        if mode == "stdio":
            asyncio.run(service.run_stdio())
        elif mode == "sse":
            default_port = port or 9001
            service.run_sse(host, default_port)
        elif mode == "streamable_http":
            default_port = port or 3001
            service.run_streamable_http(host, default_port)

    except Exception as e:
        print(f"DiFy服务启动失败: {e}")
        raise


if __name__ == "__main__":
    main()
