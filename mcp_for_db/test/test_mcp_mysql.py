import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_for_db.server.core import ServiceManager


async def comprehensive_test():
    """综合测试 MySQL MCP服务"""
    print("开始综合测试...")

    # 创建服务管理器
    service_manager = ServiceManager()
    print(f"可用服务: {service_manager.list_available_services()}")
    print(f"已配置服务: {service_manager.list_configured_services()}")

    # 创建MySQL服务
    mysql_server = service_manager.create_service("mysql")
    print(f"MySQL 服务创建成功: {mysql_server}")

    try:
        # 初始化
        print("初始化资源...")
        await mysql_server.initialize_global_resources()
        print("资源初始化完成")

        # 测试工具
        print("\n测试工具功能...")
        tool_registry = mysql_server.get_tool_registry()
        print(f"工具注册表类型: {type(tool_registry)}")

        if tool_registry:
            if hasattr(tool_registry, 'get_all_tools'):
                try:
                    tools = tool_registry.get_all_tools()
                    if asyncio.iscoroutine(tools):
                        tools = await tools

                    print(f"找到 {len(tools)} 个工具:")
                    for i, tool in enumerate(tools[:5]):  # 只显示前5个
                        print(f" {i + 1}. {tool.name}: {tool.description[:100]}...")
                    if len(tools) > 5:
                        print(f" ... 还有 {len(tools) - 5} 个工具")

                    # 测试获取单个工具
                    if tools:
                        first_tool_name = tools[0].name
                        tool = tool_registry.get_tool(first_tool_name)
                        print(f"成功获取工具: {first_tool_name}")

                except Exception as e:
                    print(f"获取工具失败: {e}")
            else:
                print("工具注册表没有 get_all_tools 方法")
        else:
            print("工具注册表为空")

        # 测试资源
        print("\n测试资源功能...")
        resource_registry = mysql_server.get_resource_registry()
        print(f"资源注册表类型: {type(resource_registry)}")

        if resource_registry:
            if hasattr(resource_registry, 'get_all_resources'):
                try:
                    resources = resource_registry.get_all_resources()
                    if asyncio.iscoroutine(resources):
                        resources = await resources

                    print(f"找到 {len(resources)} 个资源:")
                    for i, resource in enumerate(resources[:3]):  # 只显示前3个
                        print(f"{i + 1}. {resource.name}: {resource.description[:100]}...")
                    if len(resources) > 3:
                        print(f"... 还有 {len(resources) - 3} 个资源")

                except Exception as e:
                    print(f"获取资源失败: {e}")
            else:
                print("资源注册表没有 get_all_resources 方法")
        else:
            print("资源注册表为空")

        # 测试提示词
        print("\n测试提示词功能...")
        prompt_registry = mysql_server.get_prompt_registry()
        print(f"提示词注册表类型: {type(prompt_registry)}")

        if prompt_registry:
            if hasattr(prompt_registry, 'get_all_prompts'):
                try:
                    prompts = prompt_registry.get_all_prompts()
                    if asyncio.iscoroutine(prompts):
                        prompts = await prompts

                    print(f"找到 {len(prompts)} 个提示词:")
                    for i, prompt in enumerate(prompts[:3]):  # 只显示前3个
                        print(f"{i + 1}. {prompt.name}: {prompt.description[:100]}...")
                    if len(prompts) > 3:
                        print(f"... 还有 {len(prompts) - 3} 个提示词")

                except Exception as e:
                    print(f"获取提示词失败: {e}")
            else:
                print("提示词注册表没有 get_all_prompts 方法")
        else:
            print("提示词注册表为空")

        print("\n综合测试完成!")

    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 清理资源
        print("\n清理资源...")
        await mysql_server.close_global_resources()
        print("资源清理完成")


if __name__ == "__main__":
    asyncio.run(comprehensive_test())
