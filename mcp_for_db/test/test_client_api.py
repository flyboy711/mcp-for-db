import requests
import time


def print_separator(title):
    """打印分隔符"""
    print(f"\n{'=' * 60}")
    print(f"{title}")
    print('=' * 60)


def handle_response(response, test_name):
    """统一处理响应"""
    try:
        if response.status_code == 200:
            return response.json()
        else:
            print(f" {test_name} 失败:")
            print(f" 状态码: {response.status_code}")
            print(f" 响应: {response.text}")
            return None
    except Exception as e:
        print(f"{test_name} 解析响应失败: {e}")
        return None


def test_health():
    """健康检查测试"""
    print_separator("健康检查测试")

    try:
        url = "http://localhost:8000/health"
        print(f"请求: {url}")

        response = requests.get(url, timeout=10)
        result = handle_response(response, "健康检查")

        if result:
            print(f"服务状态: {result['status']}")
            print(f"服务器数量: {len(result['details'].get('servers', {}))}")
            print(f"工具总数: {result['details'].get('total_tools', 0)}")
            print(f"会话缓存: {result['details'].get('conversation_cache_size', 0)}")

            # 显示服务器状态
            servers = result['details'].get('servers', {})
            for server_name, server_info in servers.items():
                status_icon = "✅" if server_info.get('status') == 'healthy' else "❌"
                print(f"   {status_icon} {server_name}: {server_info.get('tools_count', 0)} 个工具")

            return True
        return False

    except requests.exceptions.ConnectionError:
        print("无法连接到服务器，请确保API服务已启动")
        print("启动命令: python mcp_for_db/client/api.py")
        return False
    except Exception as e:
        print(f"健康检查出错: {e}")
        return False


def test_tools():
    """获取可用工具测试"""
    print_separator("获取可用工具测试")

    try:
        url = "http://localhost:8000/tools"
        print(f"请求: {url}")

        response = requests.get(url, timeout=10)
        result = handle_response(response, "获取工具列表")

        if result:
            print(f"获取到 {len(result)} 个可用工具:")

            # 按服务器分组显示
            tools_by_server = {}
            for tool in result:
                server = tool.get('server', 'unknown')
                if server not in tools_by_server:
                    tools_by_server[server] = []
                tools_by_server[server].append(tool)

            for server_name, tools in tools_by_server.items():
                print(f"\n {server_name} ({len(tools)} 个工具):")
                for tool in tools[:5]:  # 只显示前5个
                    desc = tool['description'][:60] + "..." if len(tool['description']) > 60 else tool['description']
                    print(f" • {tool['name']}: {desc}")
                if len(tools) > 5:
                    print(f" .. 还有 {len(tools) - 5} 个工具")

            return True
        return False

    except Exception as e:
        print(f"获取工具列表出错: {e}")
        return False


def test_basic_query():
    """基本查询测试"""
    print_separator("基本查询测试")

    try:
        url = "http://localhost:8000/query"
        data = {
            "question": "显示当前数据库的基本信息",
            "include_tool_info": True
        }

        print(f"请求: {url}")
        print(f"问题: {data['question']}")

        start_time = time.time()
        response = requests.post(url, json=data, timeout=30)
        processing_time = time.time() - start_time

        result = handle_response(response, "基本查询")

        if result:
            print(f"查询成功 (用时: {processing_time:.2f}s)")
            print(f"回答: {result['answer']}")
            print(f"会话ID: {result['conversation_id']}")
            print(f"服务器处理时间: {result.get('processing_time', 0):.3f}s")

            # 显示工具调用信息
            if result.get('tool_calls'):
                print(f"\n 工具调用 ({len(result['tool_calls'])} 个):")
                for i, tool_call in enumerate(result['tool_calls'], 1):
                    status_icon = "✅" if tool_call.get('success') else "❌"
                    print(f"   {i}. {status_icon} {tool_call['tool_name']}")
                    if not tool_call.get('success'):
                        print(f" 错误: {tool_call.get('result', 'Unknown error')}")

            # 显示模型信息
            if result.get('model_info'):
                model_info = result['model_info']
                print(f"\n模型信息:")
                print(f"模型: {model_info.get('model', 'unknown')}")
                print(f"提供商: {model_info.get('provider', 'unknown')}")

            return result['conversation_id']
        return None

    except Exception as e:
        print(f"基本查询出错: {e}")
        return None


def test_conversation(conversation_id):
    """多轮对话测试"""
    print_separator("多轮对话测试")

    if not conversation_id:
        print("跳过多轮对话测试（需要上一步的会话ID）")
        return False

    try:
        url = "http://localhost:8000/query"
        data = {
            "question": "刚才查询的数据库有多少个表？",
            "conversation_id": conversation_id,
            "include_tool_info": True
        }

        print(f"请求: {url}")
        print(f"使用会话ID: {conversation_id}")
        print(f"问题: {data['question']}")

        start_time = time.time()
        response = requests.post(url, json=data, timeout=30)
        processing_time = time.time() - start_time

        result = handle_response(response, "多轮对话")

        if result:
            print(f"对话成功 (用时: {processing_time:.2f}s)")
            print(f"回答: {result['answer']}")

            # 显示工具调用
            if result.get('tool_calls'):
                print(f"\n工具调用: {len(result['tool_calls'])} 个")
                for tool_call in result['tool_calls']:
                    status_icon = "✅" if tool_call.get('success') else "❌"
                    print(f"   {status_icon} {tool_call['tool_name']}")

            return True
        return False

    except Exception as e:
        print(f"多轮对话出错: {e}")
        return False


def test_direct_tool_execution():
    """直接工具执行测试"""
    print_separator("直接工具执行测试")

    try:
        url = "http://localhost:8000/tools/execute"
        data = {
            "tool_name": "MySQLServer_show_databases",
            "tool_args": {}
        }

        print(f"请求: {url}")
        print(f"工具: {data['tool_name']}")

        response = requests.post(url, json=data, timeout=20)
        result = handle_response(response, "直接工具执行")

        if result:
            if result.get('success'):
                print(f"工具执行成功")
                print(f"结果: {str(result['result'])[:200]}...")
                print(f"执行时间: {result.get('processing_time', 0):.3f}s")
            else:
                print(f"工具执行失败: {result.get('error', 'Unknown error')}")
            return result.get('success', False)
        return False

    except Exception as e:
        print(f"直接工具执行出错: {e}")
        return False


def test_conversation_management():
    """会话管理测试"""
    print_separator("会话管理测试")

    try:
        url = "http://localhost:8000/conversations"
        print(f"请求: {url}")

        response = requests.get(url, timeout=10)
        result = handle_response(response, "获取会话列表")

        if result:
            print(f"获取到 {len(result)} 个会话:")
            for conv in result[:3]:  # 只显示前3个
                print(f"{conv['conversation_id'][:20]}...")
                print(f"消息数: {conv['message_count']}")
                print(f"摘要: {conv.get('summary', '无')[:50]}...")
                print(f"最后更新: {conv['last_updated'][:19]}")
                print()

            return True
        return False

    except Exception as e:
        print(f"会话管理测试出错: {e}")
        return False


def run_all_tests():
    """运行所有测试"""
    print("开始 API 接口测试")
    print("=" * 60)

    results = {}

    # 1. 健康检查
    results['health'] = test_health()
    if not results['health']:
        print("健康检查失败，停止后续测试")
        return

    # 2. 获取工具列表
    results['tools'] = test_tools()

    # 3. 基本查询
    conversation_id = test_basic_query()
    results['basic_query'] = conversation_id is not None

    # 4. 多轮对话
    results['conversation'] = test_conversation(conversation_id)

    # 5. 直接工具执行
    results['direct_tool'] = test_direct_tool_execution()

    # 6. 会话管理
    results['conversation_mgmt'] = test_conversation_management()

    # 总结
    print_separator("测试结果总结")
    total_tests = len(results)
    passed_tests = sum(1 for result in results.values() if result)

    print(f"测试结果: {passed_tests}/{total_tests} 通过")

    for test_name, result in results.items():
        status_icon = "✅" if result else "❌"
        test_display_name = {
            'health': '健康检查',
            'tools': '工具列表',
            'basic_query': '基本查询',
            'conversation': '多轮对话',
            'direct_tool': '直接工具执行',
            'conversation_mgmt': '会话管理'
        }.get(test_name, test_name)

        print(f"   {status_icon} {test_display_name}")

    if passed_tests == total_tests:
        print(f"\n所有测试通过！API服务运行正常")
    else:
        print(f"\n部分测试失败，请检查服务状态")


if __name__ == "__main__":
    run_all_tests()
