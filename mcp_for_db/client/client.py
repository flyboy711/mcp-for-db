import os
import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Any
from contextlib import AsyncExitStack
from enum import Enum

# 根据模型类型选择不同的客户端
try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OpenAI = None
    OPENAI_AVAILABLE = False

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_for_db.server.shared.utils import get_logger, configure_logger

# 加载环境变量
load_dotenv(os.path.join(Path(__file__).parent.parent.parent, ".env"))


class ModelProvider(Enum):
    """模型提供商枚举"""
    OPENAI = "openai"
    QWEN_COMPATIBLE = "qwen_compatible"  # 使用 OpenAI 兼容接口的 Qwen
    CUSTOM_OPENAI_COMPATIBLE = "custom_openai"


class MCPClient:
    """封装 MCP 客户端，支持多种大模型提供商"""

    def __init__(self, servers_config: Dict[str, str] = None):
        """
        初始化 MCP 客户端服务

        Args:
            servers_config: 服务器配置，形如 {"SQLServer": "path.to.mysql_server"}
        """
        # 首先初始化日志器
        self.logger = get_logger(__name__)
        self.logger.setLevel(logging.INFO)
        configure_logger("Client.log")

        self.logger.info("开始初始化 MCP 客户端...")

        self.exit_stack = AsyncExitStack()

        # 基础配置
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.model = os.getenv("MODEL", "qwen-plus")

        # 检测模型提供商
        self.provider = self._detect_provider()

        if not self.api_key:
            self.logger.error("未找到 API 密钥")
            raise ValueError("未找到API密钥，请在 .env 文件中配置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY")

        # 初始化对应的客户端
        self.client = self._initialize_client()

        # 存储服务器会话和工具信息
        self.sessions: Dict[str, ClientSession] = {}
        self.tools_by_session: Dict[str, list] = {}
        self.all_tools = []

        # 默认服务器配置
        self.servers_config = servers_config or {
            "MySQLServer": MCPClient.get_mysql_server_path(),
            "DiFyServer": MCPClient.get_dify_server_path(),
        }

        self._is_initialized = False

        self.logger.info("MCP客户端初始化完成")

    def _detect_provider(self) -> ModelProvider:
        """自动检测模型提供商"""
        model_lower = self.model.lower()

        # 检测qwen模型，统一使用OpenAI兼容接口
        if "qwen" in model_lower:
            return ModelProvider.QWEN_COMPATIBLE

        # 检测自定义base_url (OpenAI兼容接口)
        if self.base_url and "openai" not in self.base_url.lower():
            return ModelProvider.CUSTOM_OPENAI_COMPATIBLE

        # 默认使用OpenAI
        return ModelProvider.OPENAI

    def _initialize_client(self):
        """根据提供商初始化对应的客户端"""
        if not OPENAI_AVAILABLE:
            raise ImportError("使用此客户端需要安装 openai: pip install openai")

        client_kwargs = {"api_key": self.api_key}

        if self.provider == ModelProvider.QWEN_COMPATIBLE:
            # 使用 OpenAI 兼容接口访问 Qwen
            # 参考网址: https://bailian.console.aliyun.com/?tab=api&productCode=p_efm&switchAgent=12278231#/api/?type=model&url=2712576
            client_kwargs["base_url"] = self.base_url
            self.logger.info(f"使用OpenAI兼容接口访问Qwen模型: {self.model}")
            self.logger.info(f"API端点: {self.base_url}")

        elif self.provider == ModelProvider.CUSTOM_OPENAI_COMPATIBLE:
            # 自定义 OpenAI 兼容接口
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.logger.info(f"使用自定义OpenAI兼容接口: {self.base_url}")

        else:
            # 标准 OpenAI
            if self.base_url and self.base_url != "https://dashscope.aliyuncs.com/compatible-mode/v1":
                client_kwargs["base_url"] = self.base_url
            self.logger.info(f"使用标准OpenAI接口: {self.model}")

        return OpenAI(**client_kwargs)

    @staticmethod
    def get_mysql_server_path() -> str:
        """获取 MySQL 服务器脚本路径"""
        return "mcp_for_db.server.cli.mysql_entry"

    @staticmethod
    def get_dify_server_path() -> str:
        """获取 DiFy 服务器脚本路径"""
        return "mcp_for_db.server.cli.dify_entry"

    async def initialize(self):
        """初始化所有 MCP 服务器连接"""
        if self._is_initialized:
            self.logger.info("MCP服务已经初始化，跳过")
            return

        try:
            self.logger.info(f"开始初始化MCP服务 (使用 {self.provider.value})...")
            await self.connect_to_servers(self.servers_config)
            self._is_initialized = True
            self.logger.info("✅ MCP服务初始化完成")
        except Exception as e:
            self.logger.error(f"❌ MCP服务初始化失败: {e}")
            raise

    async def connect_to_servers(self, servers: dict):
        """连接到多个 MCP 服务器"""
        successful_connections = 0

        for server_name, module_path in servers.items():
            try:
                self.logger.info(f"正在连接服务器: {server_name} ({module_path})")

                session = await self._start_one_server(module_path)
                self.sessions[server_name] = session

                resp = await session.list_tools()
                self.tools_by_session[server_name] = resp.tools
                self.logger.info(f"从 {server_name} 获取到 {len(resp.tools)} 个工具")

                for tool in resp.tools:
                    function_name = f"{server_name}_{tool.name}"
                    tool_definition = {
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "description": tool.description or f"工具: {tool.name}",
                            "parameters": self._convert_input_schema(tool.inputSchema)
                        }
                    }
                    self.all_tools.append(tool_definition)

                successful_connections += 1
                self.logger.info(f"成功连接到服务器: {server_name}")

            except Exception as e:
                self.logger.error(f"连接服务器 {server_name} 失败: {e}")
                continue

        if successful_connections == 0:
            raise Exception("没有成功连接任何服务器")

        self.logger.info(f"已连接 {successful_connections}/{len(servers)} 个服务器，加载 {len(self.all_tools)} 个工具")

    def _convert_input_schema(self, input_schema: Any) -> Dict:
        """转换输入模式为函数参数格式"""
        if not input_schema:
            return {"type": "object", "properties": {}, "required": []}

        if isinstance(input_schema, dict):
            return {
                "type": input_schema.get("type", "object"),
                "properties": input_schema.get("properties", {}),
                "required": input_schema.get("required", [])
            }

        try:
            if hasattr(input_schema, 'model_dump'):
                schema_dict = input_schema.model_dump()
            elif hasattr(input_schema, 'dict'):
                schema_dict = input_schema.dict()
            else:
                schema_dict = dict(input_schema)

            return {
                "type": schema_dict.get("type", "object"),
                "properties": schema_dict.get("properties", {}),
                "required": schema_dict.get("required", [])
            }
        except Exception as e:
            self.logger.warning(f"转换输入模式失败: {e}")
            return {"type": "object", "properties": {}, "required": []}

    async def _start_one_server(self, module_path: str) -> ClientSession:
        """启动单个 MCP 服务器"""
        import sys

        # 设置环境变量
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(Path(__file__).parent.parent.parent),
            "MCP_SERVER_MODE": "1"
        })

        # 使用 python -m 方式启动模块
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", module_path],
            env=env
        )

        try:
            self.logger.debug(f"启动服务器命令: {sys.executable} -m {module_path}")
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read_stream, write_stream = stdio_transport
            session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )

            await session.initialize()
            return session

        except Exception as e:
            self.logger.error(f"启动服务器失败: {e}")
            raise Exception(f"启动服务器失败: {e}")

    async def process_query(self, user_query: str, conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """处理用户查询的核心方法"""
        if not self._is_initialized:
            await self.initialize()

        messages = conversation_history.copy() if conversation_history else []
        messages.append({"role": "user", "content": user_query})

        try:
            self.logger.info(f"处理查询: {user_query[:100]}...")

            # 统一使用 OpenAI 兼容接口
            response = await self._chat_with_tools_openai(messages)

            self.logger.info("查询处理完成")
            return {
                "success": True,
                "answer": response["answer"],
                "tool_calls": response.get("tool_calls", []),
                "messages": response["messages"]
            }

        except Exception as e:
            self.logger.error(f"处理查询失败: {e}")
            import traceback
            self.logger.error(f"详细错误信息: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e),
                "answer": "抱歉，处理您的问题时出现了错误。请检查服务器连接或稍后重试。"
            }

    async def _chat_with_tools_openai(self, messages: List[Dict]) -> Dict[str, Any]:
        """
        使用 OpenAI 兼容接口的对话处理
        参考网址: https://bailian.console.aliyun.com/?tab=api&productCode=p_efm&switchAgent=12278231#/api/?type=model&url=2712576
        """
        tool_calls_info = []
        max_iterations = 5
        iteration = 0
        response = None

        while iteration < max_iterations:
            try:
                # 为 Qwen 模型添加特殊配置
                request_kwargs = {
                    "model": self.model,
                    "messages": messages,
                }

                # 如果有工具，添加工具配置
                if self.all_tools:
                    request_kwargs["tools"] = self.all_tools

                # 为 Qwen3 模型添加特殊参数（如果需要）
                if self.provider == ModelProvider.QWEN_COMPATIBLE and "qwen3" in self.model.lower():
                    request_kwargs["extra_body"] = {"enable_thinking": False}

                self.logger.debug(f"发送请求到API (迭代 {iteration + 1})")
                response = self.client.chat.completions.create(**request_kwargs)

                if (hasattr(response.choices[0], 'finish_reason') and
                        response.choices[0].finish_reason == "tool_calls" and
                        hasattr(response.choices[0].message, 'tool_calls') and
                        response.choices[0].message.tool_calls):

                    self.logger.debug(f"检测到工具调用 (迭代 {iteration + 1})")
                    messages, tool_call_info = await self._handle_tool_calls_openai(messages, response)
                    tool_calls_info.extend(tool_call_info)
                    iteration += 1
                else:
                    # 没有工具调用，返回最终答案
                    break

            except Exception as e:
                self.logger.error(f"调用API失败: {e}")
                if "tool_calls" in str(e).lower():
                    self.logger.warning("可能是工具调用相关的错误，尝试无工具模式")
                    # 尝试不使用工具重新调用
                    try:
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=messages
                        )
                        break
                    except Exception as e2:
                        self.logger.error(f"无工具模式也失败: {e2}")
                        raise e
                else:
                    raise

        if iteration >= max_iterations:
            self.logger.warning("达到最大工具调用迭代次数")

        final_answer = ""
        if response and response.choices:
            final_answer = response.choices[0].message.content or "处理完成，但没有文本回复。"
        else:
            final_answer = "处理完成，但没有收到有效回复。"

        return {
            "answer": final_answer,
            "tool_calls": tool_calls_info,
            "messages": messages
        }

    async def _handle_tool_calls_openai(self, messages: List[Dict], response) -> tuple:
        """处理 OpenAI 的工具调用"""
        tool_calls = response.choices[0].message.tool_calls

        assistant_message = {
            "role": "assistant",
            "content": response.choices[0].message.content,
            "tool_calls": []
        }

        for tool_call in tool_calls:
            assistant_message["tool_calls"].append({
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            })

        messages.append(assistant_message)
        tool_calls_info = []

        for tool_call in tool_calls:
            tool_name = tool_call.function.name

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                self.logger.warning(f"解析工具参数失败: {e}, 参数: {tool_call.function.arguments}")
                tool_args = {}

            tool_call_record = {
                "tool_name": tool_name,
                "arguments": tool_args,
                "call_id": tool_call.id
            }

            try:
                result = await self.call_mcp_tool(tool_name, tool_args)
                tool_call_record["result"] = result
                tool_call_record["success"] = True
                self.logger.debug(f"工具调用成功: {tool_name}")
            except Exception as e:
                result = f"工具调用失败: {str(e)}"
                tool_call_record["result"] = result
                tool_call_record["success"] = False
                self.logger.error(f"工具调用失败: {tool_name}, 错误: {e}")

            tool_calls_info.append(tool_call_record)

            messages.append({
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.id,
            })

        return messages, tool_calls_info

    async def call_mcp_tool(self, tool_full_name: str, tool_args: dict) -> str:
        """调用 MCP 工具"""
        parts = tool_full_name.split("_", 1)
        if len(parts) != 2:
            raise Exception(f"无效的工具名称格式: {tool_full_name}")

        server_name, tool_name = parts
        session = self.sessions.get(server_name)
        if not session:
            raise Exception(f"找不到服务器: {server_name}")

        try:
            self.logger.debug(f"调用工具: {tool_name}，参数: {tool_args}")
            resp = await session.call_tool(tool_name, tool_args)

            if hasattr(resp, 'content'):
                if isinstance(resp.content, list):
                    return "\n".join(str(item) for item in resp.content if item)
                else:
                    return str(resp.content) if resp.content else "工具执行成功，无输出内容"
            else:
                return "工具执行成功"

        except Exception as e:
            self.logger.error(f"调用工具 {tool_name} 失败: {str(e)}")
            raise Exception(f"调用工具 {tool_name} 失败: {str(e)}")

    async def cleanup(self):
        """清理资源"""
        self.logger.info("清理 MCP 客户端资源...")
        try:
            await self.exit_stack.aclose()
            self._is_initialized = False
            self.sessions.clear()
            self.tools_by_session.clear()
            self.all_tools.clear()
            self.logger.info("✅ MCP客户端资源清理完成")
        except Exception as e:
            self.logger.error(f"清理资源时出错: {e}")

    def get_available_tools(self) -> List[Dict]:
        """获取可用工具列表"""
        return self.all_tools.copy()

    def _get_client_info(self) -> Dict[str, str]:
        """获取客户端信息，安全地处理URL对象"""
        info = {
            "provider": self.provider.value,
            "model": self.model,
        }

        # 安全地获取 base_url
        try:
            if hasattr(self.client, 'base_url'):
                base_url = self.client.base_url
                if hasattr(base_url, '__str__'):
                    info["api_endpoint"] = str(base_url)
                else:
                    info["api_endpoint"] = str(base_url)
            else:
                info["api_endpoint"] = self.base_url
        except Exception as e:
            info["api_endpoint"] = f"获取失败: {str(e)}"

        return info

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        client_info = self._get_client_info()

        status = {
            "initialized": self._is_initialized,
            "provider": client_info["provider"],
            "model": client_info["model"],
            "api_endpoint": client_info["api_endpoint"],
            "servers": {},
            "total_tools": len(self.all_tools)
        }

        for server_name, session in self.sessions.items():
            try:
                tools_resp = await session.list_tools()
                status["servers"][server_name] = {
                    "status": "healthy",
                    "tools_count": len(tools_resp.tools)
                }
            except Exception as e:
                status["servers"][server_name] = {
                    "status": "error",
                    "error": str(e)
                }

        return status


# 使用示例
async def main_test():
    """测试函数"""
    print("🚀 启动MCP客户端测试...")

    client = MCPClient()

    try:
        print("📡 初始化连接...")
        await client.initialize()

        print("🏥 执行健康检查...")
        health = await client.health_check()
        print("健康检查结果:", json.dumps(health, indent=2, ensure_ascii=False))

        print("📊 显示可用工具...")
        tools = client.get_available_tools()
        print(f"可用工具数量: {len(tools)}")
        for tool in tools[:5]:  # 只显示前5个工具
            desc = tool['function']['description']
            if len(desc) > 100:
                desc = desc[:100] + "..."
            print(f"  - {tool['function']['name']}: {desc}")
        if len(tools) > 5:
            print(f"  ... 还有 {len(tools) - 5} 个工具")

        print("\n💬 测试查询...")
        test_queries = [
            "显示所有数据库表",
            "显示当前数据库信息"
        ]

        for query in test_queries:
            print(f"\n🔍 查询: {query}")
            try:
                result = await client.process_query(query)

                if result["success"]:
                    print(f"✅ 回答: {result['answer']}")
                    if result.get("tool_calls"):
                        print(f"🔧 使用了 {len(result['tool_calls'])} 个工具")
                        for tool_call in result["tool_calls"]:
                            status = "成功" if tool_call.get('success') else "失败"
                            print(f"   - {tool_call['tool_name']}: {status}")
                else:
                    print(f"❌ 错误: {result.get('error', '未知错误')}")

            except Exception as e:
                print(f"❌ 处理查询时发生异常: {e}")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("🧹 清理资源...")
        await client.cleanup()
        print("✅ 测试完成")


# 交互式命令行模式
async def main():
    """客户端命令行入口"""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MCP数据库客户端")
    parser.add_argument("query", nargs="?", help="要执行的查询")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")
    parser.add_argument("--test", "-t", action="store_true", help="运行测试")
    parser.add_argument("--config", help="配置文件路径")

    args = parser.parse_args()

    if args.test:
        await main_test()
        return

    client = MCPClient()

    try:
        print("🔌 连接到MCP服务器...")
        await client.initialize()
        print("✅ 连接成功！\n")

        if args.interactive or not args.query:
            # 交互模式
            print("🤖 MCP数据库客户端 - 交互模式")
            print("输入 'quit', 'exit' 或 'q' 退出")
            print("输入 'help' 查看可用工具")
            print("输入 'health' 查看系统状态")

            while True:
                try:
                    query = input("\n💬 请输入您的问题: ").strip()
                    if query.lower() in ['quit', 'exit', 'q']:
                        break

                    if not query:
                        continue

                    if query.lower() == 'help':
                        tools = client.get_available_tools()
                        print(f"\n📋 可用工具 ({len(tools)} 个):")
                        for tool in tools[:10]:  # 只显示前10个
                            desc = tool['function']['description']
                            if len(desc) > 80:
                                desc = desc[:80] + "..."
                            print(f"  - {tool['function']['name']}: {desc}")
                        if len(tools) > 10:
                            print(f"  ... 还有 {len(tools) - 10} 个工具")
                        continue

                    if query.lower() == 'health':
                        health = await client.health_check()
                        print("\n🏥 系统状态:")
                        print(json.dumps(health, indent=2, ensure_ascii=False))
                        continue

                    print("🔄 处理中...")
                    result = await client.process_query(query)

                    if result["success"]:
                        print(f"✅ 回答: {result['answer']}")
                        if result.get("tool_calls"):
                            print(f"🔧 使用了 {len(result['tool_calls'])} 个工具")
                    else:
                        print(f"❌ 错误: {result.get('error', '未知错误')}")

                except KeyboardInterrupt:
                    print("\n👋 接收到中断信号，正在退出...")
                    break
                except Exception as e:
                    print(f"❌ 处理错误: {e}")

        else:
            # 单次查询模式
            print(f"🔍 处理查询: {args.query}")
            result = await client.process_query(args.query)

            if result["success"]:
                print(result["answer"])
                sys.exit(0)
            else:
                print(f"错误: {result.get('error', '未知错误')}", file=sys.stderr)
                sys.exit(1)

    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\n🧹 清理资源...")
        await client.cleanup()
        print("👋 再见！")


def cli_main():
    """同步启动入口"""
    asyncio.run(main_test())


if __name__ == "__main__":
    import sys

    # 如果有命令行参数，运行交互模式，否则运行测试
    if len(sys.argv) > 1:
        asyncio.run(main())
    else:
        cli_main()
