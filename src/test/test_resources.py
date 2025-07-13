import asyncio
import logging

from server.mcp.server_mysql import handle_get_resources, handle_read_resource
from server.mcp.server_mysql import initialize_global_resources, close_global_resources
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger("test_resources.log", logging.DEBUG)


async def test_resources():
    print("=== 测试资源加载 ===")
    await initialize_global_resources()

    resources = await handle_get_resources()
    print(f"加载了 {len(resources)} 个资源")

    if resources:
        print("\n可用资源列表:")
        for i, res in enumerate(resources, 1):
            print(f"{i}. {res.name} ({res.uri})")

        # 测试读取第一个资源
        first_resource = resources[0]
        print(f"\n读取资源: {first_resource.uri}")
        content = await handle_read_resource(first_resource.uri)
        print(f"\n资源内容片段:\n{content[:500]}...")

    # 测试完成后，显式关闭资源
    await close_global_resources()


if __name__ == "__main__":
    import os

    os.environ["MYSQL_HOST"] = "localhost"
    os.environ["MYSQL_USER"] = "root"
    os.environ["MYSQL_PASSWORD"] = "password"
    os.environ["MYSQL_DATABASE"] = "mcp_db"

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(test_resources())
    finally:
        loop.close()
