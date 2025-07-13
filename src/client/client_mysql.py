import json
import uuid
import asyncio
import sys
from typing import Optional, List, Any, Dict
from contextlib import AsyncExitStack
from datetime import datetime, date

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env

banner = r"""
    __  _____________        ____  ____        __________  ______
   /  |/  / ____/ __ \      / __ \/ __ )      / ____/ __ \/_  __/
  / /|_/ / /   / /_/ /_____/ / / / __  |_____/ / __/ /_/ / / /   
 / /  / / /___/ ____/_____/ /_/ / /_/ /_____/ /_/ / ____/ / /    
/_/  /_/\____/_/         /_____/_____/      \____/_/     /_/    

"""


def print_banner():
    print('#' * 65)
    print(banner)
    print('#' * 65)


def print_help():
    """Print help message"""
    print("\n=== 使用说明 ===")
    print("支持的命令：")
    print("1. schema [表名1 表名2 ...] - 显示数据库结构，可指定表名，默认返回所有表结构")
    print("2. sql <SQL语句> - 直接执行SQL查询（如：sql SELECT * FROM users）")
    print("3. explain <SQL语句> - 分析SQL执行计划（如：explain SELECT * FROM users）")
    print("4. db_health - 分析数据库健康状态")
    print("5. log [数量] - 显示该会话最近的查询日志，可指定数量（默认5条）")
    print("6. tables - 显示数据库中所有表")
    print("7. table_desc <表名> - 显示指定表的详细描述信息")
    print("8. quit - 退出程序")
    print("9. help - 显示帮助信息")
    print("\n注意：")
    print("- 使用'sql'命令时会直接执行SQL，不经过LLM处理")
    print("- 使用'explain'命令可以查看SQL执行计划")


class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.session_id = str(uuid.uuid4())

    async def set_session_id(self, session_id: str):
        self.session_id = session_id

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server

        Args:
            server_script_path: Path to the server script (.py or .js)
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("Server script must be a .py or .js file")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[server_script_path, "--mode=stdio"],  # 确保服务端以stdio模式运行
            env=None
        )
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
        await self.session.initialize()
        print(f"Session_id: {self.session_id}")

        # List available tools
        try:
            response = await self.session.list_tools()
            tools = response.tools
            print("\nConnected to server with tools:", [tool.name for tool in tools])
        except Exception as e:
            print(f"获取工具列表失败: {str(e)}")

        # List available resources
        try:
            resources_response = await self.session.list_resources()
            if resources_response and resources_response.resources:
                print("Available resources:", [resource.uri for resource in resources_response.resources])
            else:
                print("Available resources templates: ['logs']")
        except Exception as e:
            print(f"获取资源列表失败: {str(e)}")

    async def get_query_logs(self, limit: int = 5) -> str:
        """获取查询日志"""
        try:
            logs_response = await self.session.read_resource(f"logs://{self.session_id}/{limit}")
            return self._parse_response(logs_response)
        except Exception as e:
            return f"获取查询日志时出错: {str(e)}"

    async def get_schema(self, table_names: Optional[List[str]] = None) -> str:
        """获取数据库结构信息"""
        try:
            params = {"session_id": self.session_id}
            if table_names:
                params["table_names"] = table_names
            schema_response = await self.session.call_tool("get_schema", params)
            return self._parse_response(schema_response)
        except Exception as e:
            return f"获取数据库结构时出错: {str(e)}"

    async def query_data(self, sql: str) -> str:
        """执行SQL查询"""
        try:
            query_result = await self.session.call_tool("query_data", {
                "sql": sql,
                "session_id": self.session_id
            })
            return self._parse_response(query_result)
        except Exception as e:
            return f"执行SQL查询时出错: {str(e)}"

    async def explain_sql(self, sql: str) -> str:
        """分析SQL执行计划"""
        try:
            response = await self.session.call_tool("explain_sql", {
                "sql": sql,
                "session_id": self.session_id
            })
            return self._parse_response(response)
        except Exception as e:
            return f"分析SQL执行计划时出错: {str(e)}"

    async def analyze_db_health(self) -> str:
        """分析数据库健康状态"""
        try:
            response = await self.session.call_tool("analyze_db_health", {
                "session_id": self.session_id
            })
            return self._parse_response(response)
        except Exception as e:
            return f"分析数据库健康状态时出错: {str(e)}"

    async def get_tables(self) -> str:
        """获取数据库中所有表"""
        try:
            response = await self.session.call_tool("get_tables", {})
            return self._parse_response(response)
        except Exception as e:
            return f"获取表列表时出错: {str(e)}"

    async def get_table_description(self, table_name: str) -> str:
        """获取指定表的详细描述信息"""
        try:
            response = await self.session.call_tool("get_table_description", {
                "table_name": table_name
            })
            return self._parse_response(response)
        except Exception as e:
            return f"获取表描述时出错: {str(e)}"

    def _parse_response(self, response: Any) -> str:
        """解析服务端响应，兼容不同格式"""
        try:
            # 尝试按原方式解析
            if response and hasattr(response, 'contents') and response.contents:
                return response.contents[0].text
            # 如果没有contents属性，尝试直接获取文本
            elif hasattr(response, 'text'):
                return response.text
            # 如果是字典，尝试转为JSON字符串
            elif isinstance(response, dict):
                return json.dumps(response, ensure_ascii=False, indent=2)
            # 尝试将对象转为字符串
            else:
                return str(response)
        except Exception as e:
            return f"解析响应时出错: {str(e)}，原始响应: {str(response)[:200]}"

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP client Started!")
        print_help()

        while True:
            try:
                query = input("\nQuery: ").strip()

                if query.lower() == 'quit':
                    break

                if query.lower() == 'help':
                    print_help()
                    continue

                # 处理schema命令
                if query.lower().startswith('schema'):
                    parts = query.split()
                    table_names = None
                    if len(parts) > 1:
                        table_names = parts[1:]
                    response = await self.get_schema(table_names)
                    print(f"\n{response}")
                    continue

                # 处理sql命令
                if query.lower().startswith('sql '):
                    sql = query[4:].strip()
                    if not sql:
                        print("\n请在sql命令后提供有效的SQL语句")
                        continue
                    result = await self.query_data(sql)
                    try:
                        # 尝试自定义解析，处理特殊类型
                        result_data = self._custom_json_loads(result)
                        if result_data.get("success"):
                            print("\n查询结果:")
                            if "results" in result_data:
                                for row in result_data["results"]:
                                    # 使用自定义编码器处理特殊类型
                                    print(json.dumps(row, ensure_ascii=False, default=self._json_serial))
                            else:
                                print(json.dumps(result_data, ensure_ascii=False, indent=2, default=self._json_serial))
                        else:
                            print(f"\n查询失败: {result_data.get('error', '未知错误')}")
                    except Exception as e:
                        print(f"\n查询结果: {result}")
                    continue

                # 处理explain命令
                if query.lower().startswith('explain '):
                    sql = query[8:].strip()
                    if not sql:
                        print("\n请在explain命令后提供有效的SQL语句")
                        continue
                    result = await self.explain_sql(sql)
                    try:
                        result_data = self._custom_json_loads(result)
                        if result_data.get("success"):
                            print("\n执行计划分析:")
                            print(json.dumps(result_data.get("plan", result_data), ensure_ascii=False, indent=2,
                                             default=self._json_serial))
                        else:
                            print(f"\n分析失败: {result_data.get('error', '未知错误')}")
                    except json.JSONDecodeError:
                        print(f"\n执行计划分析结果: {result}")
                    continue

                # 处理db_health命令
                if query.lower() == 'db_health':
                    result = await self.analyze_db_health()
                    try:
                        result_data = self._custom_json_loads(result)
                        if result_data.get("success"):
                            print("\n数据库健康状态分析:")
                            print(json.dumps(result_data.get("health", result_data), ensure_ascii=False, indent=2,
                                             default=self._json_serial))
                        else:
                            print(f"\n分析失败: {result_data.get('error', '未知错误')}")
                    except json.JSONDecodeError:
                        print(f"\n健康状态分析结果: {result}")
                    continue

                # 处理log命令
                if query.lower().startswith('log'):
                    limit = 5
                    parts = query.split()
                    if len(parts) > 1:
                        try:
                            limit = int(parts[1])
                        except ValueError:
                            print("\n请输入有效的日志数量")
                            continue
                    response = await self.get_query_logs(limit)
                    print(f"\n{response}")
                    continue

                # 处理tables命令
                if query.lower() == 'tables':
                    response = await self.get_tables()
                    print(f"\n{response}")
                    continue

                # 处理table_desc命令
                if query.lower().startswith('table_desc '):
                    table_name = query[11:].strip()
                    if not table_name:
                        print("\n请提供表名")
                        continue
                    response = await self.get_table_description(table_name)
                    print(f"\n{response}")
                    continue

                print("\n未知命令，请输入'help'查看支持的命令列表")

            except Exception as e:
                print(f"\nError: {str(e)}")

    def _custom_json_loads(self, json_str: str) -> Dict:
        """自定义JSON解析，处理datetime和date类型"""
        try:
            # 尝试普通解析
            return json.loads(json_str)
        except json.JSONDecodeError:
            # 尝试处理包含特殊类型的情况
            # 这是一个简化处理，实际情况可能需要更复杂的解析逻辑
            return {"error": f"无法解析JSON结果: {json_str[:100]}..."}

    def _json_serial(self, obj: Any) -> str:
        """JSON序列化器，处理特殊类型"""
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if hasattr(obj, '__dict__'):
            return obj.__dict__  # 尝试将对象转为字典
        return str(obj)  # 最后将对象转为字符串

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()


async def main():
    print_banner()
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)

    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
