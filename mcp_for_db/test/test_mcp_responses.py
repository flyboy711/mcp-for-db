import asyncio
import json
import inspect
from contextlib import asynccontextmanager
from mcp_for_db.server.core import ServiceManager


class MockRequestContext:
    """模拟请求上下文"""

    def __init__(self):
        self.data = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


async def test_mcp_protocol_responses():
    """测试MCP协议响应格式"""
    print("=== MCP协议响应测试 ===")

    service_manager = ServiceManager()
    service = service_manager.create_service("mysql")

    try:
        # 初始化服务
        await service._initialize_global_resources()

        # 确保服务器已设置
        if hasattr(service, 'setup_server'):
            await service.setup_server()

        print("\n1. 测试 tools/list 响应:")

        # 在请求上下文中测试
        async with await service.create_request_context():
            # 直接测试工具注册表
            tool_registry = service.get_tool_registry()
            if tool_registry and hasattr(tool_registry, 'get_all_tools'):
                if asyncio.iscoroutinefunction(tool_registry.get_all_tools):
                    tools = await tool_registry.get_all_tools()
                else:
                    tools = tool_registry.get_all_tools()

                print(f"   返回工具数量: {len(tools)}")

                # 检查第一个工具的格式
                if tools:
                    first_tool = tools[0]
                    print(f"   第一个工具: {first_tool.name}")
                    print(f"   工具描述: {first_tool.description}")

                    # 安全地获取inputSchema
                    if hasattr(first_tool, 'inputSchema'):
                        try:
                            schema = first_tool.inputSchema
                            if isinstance(schema, dict):
                                print(f"   工具schema: {json.dumps(schema, indent=2)}")
                            else:
                                print(f"   工具schema类型: {type(schema)}")
                        except Exception as e:
                            print(f"   工具schema获取失败: {e}")

                    # 验证返回格式是否符合MCP协议
                    for i, tool in enumerate(tools[:3]):  # 检查前3个工具
                        try:
                            assert hasattr(tool, 'name'), f"工具缺少name属性: {tool}"
                            assert hasattr(tool, 'description'), f"工具缺少description属性: {tool}"
                            assert hasattr(tool, 'inputSchema'), f"工具缺少inputSchema属性: {tool}"
                            print(f"   ✓ 工具 {tool.name} 格式正确")
                        except AssertionError as e:
                            print(f"   ❌ 工具 {i} 格式错误: {e}")

        print("\n2. 测试 resources/list 响应:")
        async with await service.create_request_context():
            resource_registry = service.get_resource_registry()
            if resource_registry and hasattr(resource_registry, 'get_all_resources'):
                if asyncio.iscoroutinefunction(resource_registry.get_all_resources):
                    resources = await resource_registry.get_all_resources()
                else:
                    resources = resource_registry.get_all_resources()

                print(f"   返回资源数量: {len(resources)}")

                if resources:
                    first_resource = resources[0]
                    print(f"   第一个资源: {first_resource.uri}")
                    print(f"   资源名称: {first_resource.name}")

        print("\n3. 测试 prompts/list 响应:")
        async with await service.create_request_context():
            prompt_registry = service.get_prompt_registry()
            if prompt_registry and hasattr(prompt_registry, 'get_all_prompts'):
                if asyncio.iscoroutinefunction(prompt_registry.get_all_prompts):
                    prompts = await prompt_registry.get_all_prompts()
                else:
                    prompts = prompt_registry.get_all_prompts()

                print(f"   返回提示词数量: {len(prompts)}")

                if prompts:
                    first_prompt = prompts[0]
                    print(f"   第一个提示词: {first_prompt.name}")
                    print(f"   提示词描述: {first_prompt.description}")

        # 测试实际的MCP处理器调用
        print("\n4. 测试MCP处理器直接调用:")
        await test_mcp_handlers_directly(service)

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await service._close_global_resources()


async def test_mcp_handlers_directly(service):
    """直接测试MCP处理器"""
    try:
        server = service.server

        # 测试list_tools处理器
        if hasattr(server, 'list_tools'):
            print("   测试 list_tools 处理器...")
            # 模拟MCP框架调用
            tools_result = await server.list_tools()
            if hasattr(tools_result, 'tools'):
                tools = tools_result.tools
            else:
                tools = tools_result
            print(f"   ✓ list_tools 返回 {len(tools)} 个工具")

        # 测试list_resources处理器
        if hasattr(server, 'list_resources'):
            print("   测试 list_resources 处理器...")
            resources_result = await server.list_resources()
            if hasattr(resources_result, 'resources'):
                resources = resources_result.resources
            else:
                resources = resources_result
            print(f"   ✓ list_resources 返回 {len(resources)} 个资源")

        # 测试list_prompts处理器
        if hasattr(server, 'list_prompts'):
            print("   测试 list_prompts 处理器...")
            prompts_result = await server.list_prompts()
            if hasattr(prompts_result, 'prompts'):
                prompts = prompts_result.prompts
            else:
                prompts = prompts_result
            print(f"   ✓ list_prompts 返回 {len(prompts)} 个提示词")

    except Exception as e:
        print(f"   ❌ MCP处理器测试失败: {e}")
        import traceback
        traceback.print_exc()


async def test_server_setup():
    """测试服务器设置"""
    print("=== 服务器设置测试 ===")

    service_manager = ServiceManager()
    service = service_manager.create_service("mysql")

    try:
        await service._initialize_global_resources()

        # 检查服务器对象
        print(f"服务器类型: {type(service.server)}")

        # 安全地检查服务器属性
        safe_attrs = []
        for attr in dir(service.server):
            if not attr.startswith('__'):
                try:
                    # 跳过可能引起上下文错误的属性
                    if attr in ['request_context']:
                        safe_attrs.append(f"{attr} (跳过检查)")
                        continue

                    value = getattr(service.server, attr)
                    if callable(value):
                        safe_attrs.append(f"{attr} (方法)")
                    else:
                        safe_attrs.append(f"{attr} (属性)")
                except Exception as e:
                    safe_attrs.append(f"{attr} (访问失败: {str(e)[:50]})")

        print(f"服务器属性: {safe_attrs}")

        # 检查是否有setup_server方法
        if hasattr(service, 'setup_server'):
            print("✓ 发现setup_server方法")
            # 检查setup_server是否已被调用
            if hasattr(service, 'server_setup_completed'):
                print(f"  服务器设置状态: {service.server_setup_completed}")

            # 如果未设置，则设置服务器
            if not getattr(service, 'server_setup_completed', False):
                print("  正在设置服务器...")
                await service.setup_server()
                print("  ✓ 服务器设置完成")
            else:
                print("  服务器已经设置完成")
        else:
            print("❌ 未发现setup_server方法")

    except Exception as e:
        print(f"❌ 服务器设置测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await service._close_global_resources()


async def check_mcp_compatibility_fixed(service):
    """修复后的MCP兼容性检查"""
    print("=== MCP兼容性检查（修复版）===")

    checks_passed = 0
    total_checks = 6

    try:
        await service._initialize_global_resources()

        # 确保服务器已设置
        if hasattr(service, 'setup_server') and not getattr(service, 'server_setup_completed', False):
            await service.setup_server()

        # 所有检查都在请求上下文中进行
        async with await service.create_request_context():

            # 检查1: 注册表是否存在
            tool_registry = service.get_tool_registry()
            prompt_registry = service.get_prompt_registry()
            resource_registry = service.get_resource_registry()

            if all([tool_registry, prompt_registry, resource_registry]):
                print("✓ 所有注册表已初始化")
                checks_passed += 1
            else:
                print("❌ 部分注册表未初始化")
                print(f"  工具注册表: {tool_registry is not None}")
                print(f"  提示词注册表: {prompt_registry is not None}")
                print(f"  资源注册表: {resource_registry is not None}")

            # 检查2: 工具格式
            if tool_registry and hasattr(tool_registry, 'get_all_tools'):
                tools = await tool_registry.get_all_tools() if asyncio.iscoroutinefunction(
                    tool_registry.get_all_tools) else tool_registry.get_all_tools()
                if tools and all(
                        hasattr(t, 'name') and hasattr(t, 'description') and hasattr(t, 'inputSchema') for t in tools):
                    print(f"✓ {len(tools)} 个工具格式正确")
                    checks_passed += 1
                else:
                    print(f"❌ 工具格式不正确（工具数量: {len(tools) if tools else 0}）")
                    if tools:
                        tool = tools[0]
                        print(
                            f"  示例工具属性: name={hasattr(tool, 'name')}, description={hasattr(tool, 'description')}, inputSchema={hasattr(tool, 'inputSchema')}")

            # 检查3: 提示词格式
            if prompt_registry and hasattr(prompt_registry, 'get_all_prompts'):
                prompts = await prompt_registry.get_all_prompts() if asyncio.iscoroutinefunction(
                    prompt_registry.get_all_prompts) else prompt_registry.get_all_prompts()
                if prompts and all(hasattr(p, 'name') and hasattr(p, 'description') for p in prompts):
                    print(f"✓ {len(prompts)} 个提示词格式正确")
                    checks_passed += 1
                else:
                    print(f"❌ 提示词格式不正确（提示词数量: {len(prompts) if prompts else 0}）")

            # 检查4: 资源格式
            if resource_registry and hasattr(resource_registry, 'get_all_resources'):
                resources = await resource_registry.get_all_resources() if asyncio.iscoroutinefunction(
                    resource_registry.get_all_resources) else resource_registry.get_all_resources()
                if resources and all(hasattr(r, 'uri') and hasattr(r, 'name') for r in resources):
                    print(f"✓ {len(resources)} 个资源格式正确")
                    checks_passed += 1
                else:
                    print(f"❌ 资源格式不正确（资源数量: {len(resources) if resources else 0}）")

            # 检查5: 服务器装饰器注册
            if hasattr(service, 'server_setup_completed') and service.server_setup_completed:
                print("✓ 服务器设置已完成（装饰器应已注册）")
                checks_passed += 1
            else:
                print("❌ 服务器设置未完成")

            # 检查6: 请求上下文（当前就在上下文中，说明成功）
            print("✓ 请求上下文工作正常")
            checks_passed += 1

        print(f"\n兼容性检查结果: {checks_passed}/{total_checks} 通过")

        if checks_passed >= 4:  # 4/6通过即可
            print("🎉 您的MCP服务基本兼容，大模型应该能发现工具和资源！")
            return True
        else:
            print("⚠️  存在兼容性问题，可能影响大模型发现功能")
            return False

    except Exception as e:
        print(f"❌ 兼容性检查异常: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await service._close_global_resources()


async def test_database_connection():
    """测试数据库连接"""
    print("=== 数据库连接测试 ===")

    service_manager = ServiceManager()
    service = service_manager.create_service("mysql")

    try:
        # 不初始化全局资源，只测试配置
        print("数据库配置测试（不建立实际连接）:")

        # 检查数据库管理器
        if hasattr(service, 'db_manager'):
            db_manager = service.db_manager
            print(f"✓ 数据库管理器: {type(db_manager)}")
        else:
            print("❌ 未找到数据库管理器")

        # 检查配置
        if hasattr(service, 'config'):
            config = service.config
            print(f"✓ 服务配置: {type(config)}")

            # 安全地检查数据库配置
            if hasattr(config, 'database'):
                db_config = config.database
                print(f"✓ 数据库配置存在")
                # 不打印敏感信息，只检查配置结构
                config_attrs = [attr for attr in dir(db_config) if not attr.startswith('_')]
                print(f"  配置属性: {config_attrs}")
            else:
                print("❌ 未找到数据库配置")

    except Exception as e:
        print(f"❌ 数据库连接测试失败: {e}")
        import traceback
        traceback.print_exc()


# 使用示例
if __name__ == "__main__":
    async def main():
        # 先测试数据库配置（不建立连接）
        await test_database_connection()
        print("\n" + "=" * 50 + "\n")

        # 测试服务器设置
        await test_server_setup()
        print("\n" + "=" * 50 + "\n")

        # 测试协议响应
        await test_mcp_protocol_responses()
        print("\n" + "=" * 50 + "\n")

        # 兼容性检查
        service_manager = ServiceManager()
        service = service_manager.create_service("mysql")
        await check_mcp_compatibility_fixed(service)


    asyncio.run(main())