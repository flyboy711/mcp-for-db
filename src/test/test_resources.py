import asyncio
import os

from dotenv import load_dotenv
from server.config import SessionConfigManager, DatabaseManager
from server.config.request_context import get_current_database_manager
from server.mcp.server_mysql import handle_get_resources, handle_read_resource
from server.config import RequestContext


async def test_resources():
    print("=== 测试资源加载 ===")
    await get_current_database_manager().initialize_pool()

    resources = await handle_get_resources()
    print(f"加载了 {len(resources)} 个资源")

    if resources:
        print("\n可用资源列表:")
        for i, res in enumerate(resources, 1):
            print(f"{i}. {res.name} ({res.uri})")

        # 测试读取第一个资源
        first_resource = resources[-1]
        print(f"\n读取资源: {first_resource.uri}")
        content = await handle_read_resource(first_resource.uri)
        print(f"\n资源内容片段:\n{content[:500]}...")

    # 测试完成后，显式关闭资源
    await get_current_database_manager().close_pool()


async def main2():
    # 获取当前文件所在目录的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 获取项目根目录
    root_dir = os.path.dirname(current_dir)
    env_path = os.path.join(root_dir, "server", "config", ".env")
    load_dotenv(env_path)

    # 创建会话配置管理器 - 基于全局默认配置
    session_config = SessionConfigManager()

    # 创建数据库管理器
    db_manager = DatabaseManager(session_config)

    # 设置请求上下文
    async with RequestContext(session_config, db_manager):
        await test_resources()


if __name__ == "__main__":
    asyncio.run(main2())
