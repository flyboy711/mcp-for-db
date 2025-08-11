import asyncio
import click

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.core import ServiceManager, EnvDistributor
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger("mcp_server_cli.log")
logger.setLevel(LOG_LEVEL)

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
@click.option("--port", type=int, help="端口号")
@click.option("--oauth", is_flag=True, help="启用OAuth认证")
def dify_main(mode, host, port, oauth):
    """DiFy MCP 服务启动器"""

    if mode == "stdio":
        """此处需要把 os.environ 分发更新到各个服务配置文件 envs/ 中，否则用户配置的不起作用，还是系统默认的配置信息"""
        # 创建环境变量分发器
        env_distributor = EnvDistributor()
        # 指定启动的服务
        enabled_services = ['dify']

        # 验证配置完整性
        validation_result = env_distributor.validate_stdio_config(enabled_services=enabled_services)

        # 检查是否所有启动的服务都配置正确
        all_valid = all(validation_result.values())

        if not all_valid:
            invalid_services = [service for service, valid in validation_result.items() if not valid]
            logger.error(f"以下服务配置无效: {invalid_services}")
            logger.error("请检查环境变量配置后重试")
            raise SystemExit(1)

        logger.info("所有启动服务配置验证通过")

        # 分发环境变量到配置文件
        env_distributor.distribute_env_vars(enabled_services)

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
            service.run_streamable_http(host, default_port, oauth=oauth)

    except Exception as e:
        logger.error(f"DiFy服务启动失败: {e}")
        raise


if __name__ == "__main__":
    dify_main()
