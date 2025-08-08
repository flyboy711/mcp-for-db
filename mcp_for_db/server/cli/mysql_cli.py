import asyncio
import os

import click
from mcp_for_db.server.core import ServiceManager

"""
客户端与服务端通信时，采用 stdio 时需要注意：
⚠️⚠️⚠️
{
  "mcpServers": {
    "dba/mcp-for-db": {
      "command": "uvx",
      "args": [
        "mcp-for-db@0.9.0",
        "--mode",
        "stdio"
      ],
      "env": {
        "MYSQL_HOST": "<填写主机（必填）>",
        "MYSQL_PORT": "<填写端口（必填）>",
        "MYSQL_USER": "<填写用户名（必填）>",
        "MYSQL_PASSWORD": "<填写密码（必填）>",
        "MYSQL_DATABASE": "<填写访问的数据库（必填）>"
      }
    }
  }
}
这里的 env 会加载到进程内存中，而服务端实现时均默认是从 envs 目录下的各个服务配置信息重新加载的
"""


@click.command()
@click.option("--mode", default="stdio", type=click.Choice(["stdio", "sse", "streamable_http"]), help="运行模式")
@click.option("--host", default="0.0.0.0", help="主机地址")
@click.option("--port", type=int, help="端口号（SSE默认9000，HTTP默认3000）")
@click.option("--oauth", is_flag=True, help="启用OAuth认证")
def mysql_main(mode, host, port, oauth):
    """MySQL MCP 服务启动器"""

    service_manager = ServiceManager()

    try:
        service = service_manager.create_service("mysql")

        if mode == "stdio":
            """此处需要把 os.environ 分发更新到各个服务配置文件 envs/ 中，否则用户配置的不起作用，还是系统默认的配置信息"""
            print(os.environ)

            asyncio.run(service.run_stdio())
        elif mode == "sse":
            default_port = port or 9000
            service.run_sse(host, default_port)
        elif mode == "streamable_http":
            default_port = port or 3000
            service.run_streamable_http(host, default_port, oauth=oauth)

    except Exception as e:
        print(f"MySQL服务启动失败: {e}")
        raise


if __name__ == "__main__":
    mysql_main()
