import json
import os
import asyncio
import sys
import time
from contextlib import AsyncExitStack
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters, stdio_client
from openai import OpenAI
from mcp_for_db import LOG_LEVEL
from mcp_for_db.debug.mcp_logger import MCPCommunicationLogger

from mcp_for_db.server.shared.utils import get_logger, configure_logger

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stdin.reconfigure(encoding='utf-8', errors='replace')


class ModelProvider(Enum):
    """模型提供商枚举：对应不同提供商可能对应不同的客户端调用方式"""
    OPENAI = "openai"
    QWEN_COMPATIBLE = "qwen_compatible"
    CUSTOM_OPENAI_COMPATIBLE = "custom_openai"


class OptimizedTaskProcessor:
    """优化任务处理 - 仅通过提示词模板进行编排"""

    def __init__(self, mcp_client):
        self.client = mcp_client
        self.logger = mcp_client.logger
        self.mcp_logger = mcp_client.mcp_logger

        # 提示词模板映射
        self.prompt_templates = {
            "data_query": "query-table-data-prompt",
            "admin_task": "smart-tools-prompt"
        }

    async def process_query(self, user_query: str, conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """处理查询 - 仅使用提示词优化"""
        start_time = time.time()
        self.mcp_logger.log_query_processing(user_query)

        try:
            # 检查是否需要特殊提示词
            enhanced_prompt = await self._get_simple_prompt(user_query)

            # 构建消息
            messages = conversation_history.copy() if conversation_history else []

            if enhanced_prompt:
                if not any(msg.get("role") == "system" for msg in messages):
                    messages.insert(0, {"role": "system", "content": enhanced_prompt})

            messages.append({"role": "user", "content": user_query})

            # 执行查询 - 使用所有工具
            response = await self._execute_with_all_tools(messages)

            return {
                "success": True,
                "answer": response["answer"],
                "tool_calls": response.get("tool_calls", []),
                "messages": response["messages"],
                "optimization_used": bool(enhanced_prompt),
                "prompt_type": self._get_prompt_type(user_query) if enhanced_prompt else None,
                "tools_used": len(self.client.all_tools),
                "execution_time": time.time() - start_time
            }

        except Exception as e:
            self.logger.error(f"处理查询失败: {e}")
            # 回退到标准处理
            return await self._fallback_process(user_query, conversation_history)

    def _get_prompt_type(self, query: str) -> str:
        """确定提示词类型"""
        query_lower = query.lower()

        if any(kw in query_lower for kw in ["查询", "显示", "获取", "数据"]):
            return "data_query"
        elif any(kw in query_lower for kw in ["诊断", "优化", "性能", "分析"]):
            return "admin_task"
        else:
            return "general"

    async def _get_simple_prompt(self, query: str) -> Optional[str]:
        """获取简化提示词"""
        query_lower = query.lower()

        try:
            # 数据查询类任务
            if any(kw in query_lower for kw in ["查询", "显示", "获取", "数据", "表", "字段"]):
                return await self.client.get_prompt("query-table-data-prompt", {"desc": query})

            # 管理诊断类任务
            elif any(kw in query_lower for kw in ["诊断", "优化", "性能", "分析"]):
                return await self.client.get_prompt("smart-tools-prompt", {"task": query})

        except Exception as e:
            self.logger.debug(f"获取提示词失败，使用默认处理: {e}")

        return None

    async def _execute_with_all_tools(self, messages: List[Dict]) -> Dict[str, Any]:
        """使用所有工具执行查询"""
        start_time = time.time()

        response = await self.client._chat_with_tools_direct(messages, self.client.all_tools)

        exec_time = time.time() - start_time
        self.mcp_logger.log_llm_interaction(
            model=self.client.model,
            messages=messages,
            response=response.get("answer", "")[:500],
            execution_time=exec_time
        )

        return response

    async def _fallback_process(self, user_query: str,
                                conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """回退处理"""
        self.logger.info("使用回退处理模式")
        return await self.client._process_query_standard(user_query, conversation_history)


class MCPClient:
    """MCP 客户端"""

    def __init__(self, servers_config: Dict[str, str] = None):
        self.logger = get_logger(__name__)
        self.logger.setLevel(LOG_LEVEL)
        configure_logger("mcp_client.log")

        self.logger.info("开始初始化 MCP 客户端...")
        self.mcp_logger = MCPCommunicationLogger()
        self.exit_stack = AsyncExitStack()

        # 加载配置
        load_dotenv(Path(__file__).parent.parent / "envs/.env")
        self.api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.model = os.getenv("MODEL", "qwen-plus")

        self.provider = self._detect_provider()

        if not self.api_key:
            raise ValueError("未找到API密钥")

        self.client = self._initialize_client()

        # 存储信息
        self.sessions: Dict[str, ClientSession] = {}
        self.tools_by_session: Dict[str, list] = {}
        self.all_tools = []
        self.prompts_by_session: Dict[str, list] = {}
        self.all_prompts = []

        self.servers_config = servers_config or {
            "MySQLServer": "mcp_for_db.server.cli.mysql_cli",
            "DiFyServer": "mcp_for_db.server.cli.dify_cli",
        }

        self._is_initialized = False
        self.logger.info("MCP客户端初始化完成")

    def _detect_provider(self) -> ModelProvider:
        model_lower = self.model.lower()
        if "qwen" in model_lower:
            return ModelProvider.QWEN_COMPATIBLE
        if self.base_url and "openai" not in self.base_url.lower():
            return ModelProvider.CUSTOM_OPENAI_COMPATIBLE
        return ModelProvider.OPENAI

    def _initialize_client(self):
        client_kwargs = {"api_key": self.api_key}

        if self.provider == ModelProvider.QWEN_COMPATIBLE:
            client_kwargs["base_url"] = self.base_url
        elif self.provider == ModelProvider.CUSTOM_OPENAI_COMPATIBLE:
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
        else:
            if self.base_url and self.base_url != "https://dashscope.aliyuncs.com/compatible-mode/v1":
                client_kwargs["base_url"] = self.base_url

        return OpenAI(**client_kwargs)

    async def initialize(self):
        if self._is_initialized:
            return

        try:
            await self.connect_to_servers(self.servers_config)
            self._is_initialized = True
            self.logger.info("MCP服务初始化完成")
        except Exception as e:
            self.logger.error(f"MCP服务初始化失败: {e}")
            raise

    async def process_query(self, user_query: str,
                            conversation_history: List[Dict] = None,
                            use_optimization: bool = True) -> Dict[str, Any]:
        """处理查询 - 使用优化的处理器"""
        if not self._is_initialized:
            await self.initialize()

        if use_optimization:
            processor = OptimizedTaskProcessor(self)
            return await processor.process_query(user_query, conversation_history)
        else:
            return await self._process_query_standard(user_query, conversation_history)

    async def _chat_with_tools_direct(self, messages: List[Dict],
                                      tools: List[Dict]) -> Dict[str, Any]:
        """直接使用指定工具进行对话"""
        tool_calls_info = []
        max_iterations = 5
        iteration = 0
        response = None

        while iteration < max_iterations:
            try:
                request_kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "tools": tools
                }

                if self.provider == ModelProvider.QWEN_COMPATIBLE and "qwen3" in self.model.lower():
                    request_kwargs["extra_body"] = {"enable_thinking": False}

                response = self.client.chat.completions.create(**request_kwargs)

                if (hasattr(response.choices[0], 'finish_reason') and
                        response.choices[0].finish_reason == "tool_calls" and
                        hasattr(response.choices[0].message, 'tool_calls') and
                        response.choices[0].message.tool_calls):

                    messages, tool_call_info = await self._handle_tool_calls_openai(messages, response)
                    tool_calls_info.extend(tool_call_info)
                    iteration += 1
                else:
                    break

            except Exception as e:
                self.logger.error(f"API调用失败: {e}")
                if iteration == 0:  # 第一次失败，尝试无工具模式
                    response = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages
                    )
                    break
                else:
                    raise

        final_answer = ""
        if response and response.choices:
            final_answer = response.choices[0].message.content or "处理完成"

        return {
            "answer": final_answer,
            "tool_calls": tool_calls_info,
            "messages": messages
        }

    async def connect_to_servers(self, servers: dict):
        successful_connections = 0

        for server_name, module_path in servers.items():
            try:
                start_time = time.time()
                session = await self._start_one_server(module_path)
                self.sessions[server_name] = session

                # 获取工具和提示词
                resp = await session.list_tools()
                self.tools_by_session[server_name] = resp.tools

                try:
                    prompts_resp = await session.list_prompts()
                    self.prompts_by_session[server_name] = prompts_resp.prompts
                    self.all_prompts.extend(prompts_resp.prompts)
                except RuntimeError:
                    self.prompts_by_session[server_name] = []

                # 处理工具定义
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
                exec_time = time.time() - start_time
                self.logger.info(f"连接 {server_name}: {len(resp.tools)}工具 ({exec_time:.1f}s)")

            except Exception as e:
                self.logger.error(f"连接 {server_name} 失败: {e}")
                continue

        if successful_connections == 0:
            raise Exception("没有成功连接任何服务器")

        self.logger.info(f"已连接 {successful_connections} 个服务器，加载 {len(self.all_tools)} 个工具")

    async def get_prompt(self, prompt_name: str, arguments: Dict[str, Any] = None) -> str:
        target_server = None
        target_prompt = None

        for server_name, prompts in self.prompts_by_session.items():
            for prompt in prompts:
                if prompt.name == prompt_name:
                    target_server = server_name
                    target_prompt = prompt
                    break
            if target_prompt:
                break

        if not target_prompt:
            raise Exception(f"找不到提示词: {prompt_name}")

        session = self.sessions[target_server]
        try:
            resp = await session.get_prompt(prompt_name, arguments or {})
            if hasattr(resp, 'messages') and resp.messages:
                content_parts = []
                for message in resp.messages:
                    if hasattr(message, 'content'):
                        if hasattr(message.content, 'text'):
                            content_parts.append(message.content.text)
                        elif isinstance(message.content, str):
                            content_parts.append(message.content)
                return "\n".join(content_parts)
            return "提示词执行成功"
        except Exception as e:
            raise Exception(f"获取提示词失败: {str(e)}")

    def _convert_input_schema(self, input_schema: Any) -> Dict:
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
        except RuntimeError:
            return {"type": "object", "properties": {}, "required": []}

    async def _start_one_server(self, module_path: str) -> ClientSession:
        import sys
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(Path(__file__).parent.parent.parent),
            "MCP_SERVER_MODE": "1"
        })

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", module_path],
            env=env
        )

        stdio_transport = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = stdio_transport
        session = await self.exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )

        await session.initialize()
        return session

    async def _process_query_standard(self, user_query: str,
                                      conversation_history: List[Dict] = None) -> Dict[str, Any]:
        # 保持原有逻辑
        messages = conversation_history.copy() if conversation_history else []
        messages.append({"role": "user", "content": user_query})

        try:
            response = await self._chat_with_tools_openai(messages)
            return {
                "success": True,
                "answer": response["answer"],
                "tool_calls": response.get("tool_calls", []),
                "messages": response["messages"],
                "optimization_used": False,
                "tools_used": len(self.all_tools)
            }
        except Exception:
            raise

    async def _chat_with_tools_openai(self, messages: List[Dict]) -> Dict[str, Any]:
        # 直接使用 all_tools
        return await self._chat_with_tools_direct(messages, self.all_tools)

    async def _handle_tool_calls_openai(self, messages: List[Dict], response) -> tuple:
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
            error = None
            start_time = time.time()

            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                tool_args = {}
                error = f"参数解析失败: {e}"

            tool_call_record = {
                "tool_name": tool_name,
                "arguments": tool_args,
                "call_id": tool_call.id
            }

            try:
                if not error:
                    result = await self.call_mcp_tool(tool_name, tool_args)
                    tool_call_record["result"] = result
                    tool_call_record["success"] = True
                else:
                    result = error
                    tool_call_record["result"] = result
                    tool_call_record["success"] = False
            except Exception as e:
                result = f"工具调用失败: {str(e)}"
                tool_call_record["result"] = result
                tool_call_record["success"] = False
                error = str(e)

            tool_calls_info.append(tool_call_record)

            messages.append({
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.id,
            })

            exec_time = time.time() - start_time
            self.mcp_logger.log_tool_call(
                server_name=tool_name.split("_")[0],
                tool_name=tool_name,
                arguments=tool_args,
                result=result[:500] if result else None,
                success=error is None,
                error=error,
                execution_time=exec_time
            )

        return messages, tool_calls_info

    async def call_mcp_tool(self, tool_full_name: str, tool_args: dict) -> str:
        parts = tool_full_name.split("_", 1)
        if len(parts) != 2:
            raise Exception(f"无效的工具名称格式: {tool_full_name}")

        server_name, tool_name = parts
        session = self.sessions.get(server_name)
        if not session:
            raise Exception(f"找不到服务器: {server_name}")

        try:
            resp = await session.call_tool(tool_name, tool_args)

            if hasattr(resp, 'content'):
                if isinstance(resp.content, list):
                    return "\n".join(str(item) for item in resp.content if item)
                else:
                    return str(resp.content) if resp.content else "工具执行成功"
            else:
                return "工具执行成功"
        except Exception as e:
            raise Exception(f"调用工具 {tool_name} 失败: {str(e)}")

    async def cleanup(self):
        try:
            await self.exit_stack.aclose()
            self._is_initialized = False
            self.sessions.clear()
            self.tools_by_session.clear()
            self.all_tools.clear()
            self.prompts_by_session.clear()
            self.all_prompts.clear()
            self.logger.info("资源清理完成")
        except Exception as e:
            self.logger.error(f"清理资源出错: {e}")

    def get_available_tools(self) -> List[Dict]:
        return self.all_tools.copy()

    def get_available_prompts(self) -> List[Dict]:
        """获取可用提示词列表"""
        prompts_info = []
        for server_name, prompts in self.prompts_by_session.items():
            for prompt in prompts:
                prompt_info = {
                    "server": server_name,
                    "name": prompt.name,
                    "description": prompt.description or "无描述",
                    "arguments": []
                }

                # 安全处理参数
                if hasattr(prompt, 'arguments') and prompt.arguments:
                    try:
                        for arg in prompt.arguments:
                            if hasattr(arg, 'name'):
                                # PromptArgument 对象
                                arg_info = {
                                    "name": arg.name,
                                    "description": getattr(arg, 'description', ''),
                                    "required": getattr(arg, 'required', False)
                                }
                            elif hasattr(arg, 'dict'):
                                # Pydantic 模型
                                arg_dict = arg.dict()
                                arg_info = {
                                    "name": arg_dict.get('name', 'unknown'),
                                    "description": arg_dict.get('description', ''),
                                    "required": arg_dict.get('required', False)
                                }
                            elif isinstance(arg, dict):
                                # 字典对象
                                arg_info = {
                                    "name": arg.get('name', 'unknown'),
                                    "description": arg.get('description', ''),
                                    "required": arg.get('required', False)
                                }
                            else:
                                # 其他类型，转为字符串
                                arg_info = {
                                    "name": str(arg),
                                    "description": '',
                                    "required": False
                                }
                            prompt_info["arguments"].append(arg_info)
                    except Exception as e:
                        self.logger.debug(f"处理提示词 {prompt.name} 参数时出错: {e}")
                        prompt_info["arguments"] = []

                prompts_info.append(prompt_info)
        return prompts_info

    async def health_check(self) -> Dict[str, Any]:
        client_info = {
            "provider": self.provider.value,
            "model": self.model,
        }

        status = {
            "initialized": self._is_initialized,
            "provider": client_info["provider"],
            "model": client_info["model"],
            "servers": {},
            "total_tools": len(self.all_tools),
            "total_prompts": len(self.all_prompts)
        }

        for server_name, session in self.sessions.items():
            try:
                tools_resp = await session.list_tools()
                prompts_count = len(self.prompts_by_session.get(server_name, []))
                status["servers"][server_name] = {
                    "status": "healthy",
                    "tools_count": len(tools_resp.tools),
                    "prompts_count": prompts_count
                }
            except Exception as e:
                status["servers"][server_name] = {
                    "status": "error",
                    "error": str(e)
                }

        return status


async def main_test():
    print("启动 MCP 客户端测试...")
    client = MCPClient()

    try:
        await client.initialize()
        health = await client.health_check()
        print("健康检查:", json.dumps(health, indent=2, ensure_ascii=False))

        test_queries = [
            "显示当前数据库的基本信息",
            "显示所有数据库表",
            "查询用户表t_users的结构信息",
        ]

        for query in test_queries:
            print(f"\n查询: {query}")
            result = await client.process_query(query, use_optimization=True)
            if result["success"]:
                print(f"回答: {result['answer'][:200]}...")
                print(f"工具: {result.get('tools_used', 0)}个, 耗时: {result.get('execution_time', 0):.2f}s")
            else:
                print(f"错误: {result.get('error')}")
    finally:
        await client.cleanup()


async def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="MCP 数据库客户端 (支持智能提示词优化)")
    parser.add_argument("--query", nargs="?", help="要执行的查询")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")
    parser.add_argument("--test", "-t", action="store_true", help="运行测试")
    parser.add_argument("--no-optimize", action="store_true", help="禁用智能优化")

    args = parser.parse_args()

    if args.test:
        await main_test()
        return

    client = MCPClient()

    try:
        print("连接到 MCP 服务器...")
        await client.initialize()
        print("连接成功！\n")

        if args.interactive or not args.query:
            print("🚀 MCP 数据库客户端 - 智能交互模式")
            print("=" * 50)
            print("命令说明:")
            print("  quit/exit/q    - 退出程序")
            print("  help           - 查看可用工具")
            print("  prompts        - 查看可用提示词")
            print("  health         - 查看系统状态")
            print("  opt on/off     - 开启/关闭智能优化")
            print("=" * 50)

            optimization_enabled = not args.no_optimize
            print(f"智能优化: {'开启' if optimization_enabled else '关闭'}")

            conversation_history = []

            while True:
                try:
                    query = input(f"\n{'🧠' if optimization_enabled else '💻'} 请输入您的问题: ").strip()
                    if not query:
                        continue

                    if query.lower() in ['quit', 'exit', 'q']:
                        break

                    # 修复提示词显示逻辑
                    if query.lower() == 'prompts':
                        prompts = client.get_available_prompts()
                        print(f"\n可用提示词 ({len(prompts)} 个):")
                        for i, prompt in enumerate(prompts[:10], 1):
                            print(f"{i:2d}. {prompt['name']}")
                            desc = prompt['description']
                            print(f" 描述: {desc[:80]}{'...' if len(desc) > 80 else ''}")

                            # 修复参数处理逻辑
                            if prompt.get('arguments'):
                                try:
                                    args_list = []
                                    for arg in prompt['arguments']:
                                        # 处理 PromptArgument 对象
                                        if hasattr(arg, 'name'):
                                            arg_name = arg.name
                                        elif hasattr(arg, 'dict'):
                                            arg_dict = arg.dict()
                                            arg_name = arg_dict.get('name', 'unknown')
                                        elif isinstance(arg, dict):
                                            arg_name = arg.get('name', 'unknown')
                                        else:
                                            arg_name = str(arg)
                                        args_list.append(arg_name)

                                    if args_list:
                                        print(f" 参数: {', '.join(args_list)}")
                                except Exception as e:
                                    print(f" 参数: (解析失败: {e})")

                        if len(prompts) > 10:
                            print(f"\n... 还有 {len(prompts) - 10} 个提示词")
                        continue

                    # 其他命令保持不变...
                    if query.lower().startswith('opt '):
                        setting = query[4:].strip().lower()
                        if setting == 'on':
                            optimization_enabled = True
                            print("✅ 智能优化已开启")
                        elif setting == 'off':
                            optimization_enabled = False
                            print("❌ 智能优化已关闭")
                        else:
                            print("用法: opt on/off")
                        continue

                    if query.lower() == 'help':
                        tools = client.get_available_tools()
                        print(f"\n可用工具 ({len(tools)} 个):")
                        for i, tool in enumerate(tools[:10], 1):
                            name = tool['function']['name']
                            desc = tool['function']['description']
                            print(f"{i:2d}. {name}")
                            print(f"    {desc[:80]}{'...' if len(desc) > 80 else ''}")
                        if len(tools) > 10:
                            print(f"\n... 还有 {len(tools) - 10} 个工具")
                        continue

                    if query.lower() == 'health':
                        health = await client.health_check()
                        print("\n系统状态:")
                        print(f"初始化状态: {'✅' if health['initialized'] else '❌'}")
                        print(f"模型提供商: {health['provider']}")
                        print(f"使用模型: {health['model']}")
                        print(f"总工具数: {health['total_tools']}")
                        print(f"总提示词数: {health['total_prompts']}")
                        print("\n服务器状态:")
                        for server_name, server_info in health['servers'].items():
                            status_icon = "✅" if server_info['status'] == 'healthy' else "❌"
                            print(
                                f"  {status_icon} {server_name}: {server_info.get('tools_count', 0)} 工具, {server_info.get('prompts_count', 0)} 提示词")
                            if server_info['status'] != 'healthy':
                                print(f" 错误: {server_info.get('error', '未知错误')}")
                        continue

                    if query.lower() in ['clear', 'cls']:
                        conversation_history = []
                        print("对话历史已清空")
                        continue

                    if query.lower() == 'history':
                        print(f"\n对话历史 ({len(conversation_history)} 条):")
                        for i, msg in enumerate(conversation_history[-10:], 1):
                            role_icon = "🤖" if msg['role'] == 'assistant' else "👤"
                            content = msg['content'][:100] + "..." if len(msg['content']) > 100 else msg['content']
                            print(f"{i:2d}. {role_icon} {msg['role']}: {content}")
                        if len(conversation_history) > 10:
                            print(f"\n... 还有 {len(conversation_history) - 10} 条历史记录")
                        continue

                    # 处理查询
                    print(f"🔄 处理中... ({'🧠智能优化' if optimization_enabled else '💻 标准模式'})")
                    start_time = time.time()

                    result = await client.process_query(
                        query,
                        conversation_history=conversation_history.copy() if conversation_history else None,
                        use_optimization=optimization_enabled
                    )

                    if result["success"]:
                        print(f"\n回答:")
                        print(result['answer'])

                        # 更新对话历史
                        conversation_history.append({"role": "user", "content": query})
                        conversation_history.append({"role": "assistant", "content": result['answer']})

                        # 保持历史记录在合理范围内
                        if len(conversation_history) > 20:
                            conversation_history = conversation_history[-20:]

                        # 显示执行信息
                        info_parts = []
                        if result.get("tool_calls"):
                            successful_calls = sum(1 for call in result["tool_calls"] if call.get("success", True))
                            info_parts.append(f"工具调用: {successful_calls}/{len(result['tool_calls'])}次成功")
                        if result.get("tools_used"):
                            info_parts.append(f"可用工具: {result['tools_used']}个")
                        if result.get("optimization_used"):
                            opt_type = result.get('prompt_type', 'unknown')
                            info_parts.append(f"优化类型: {opt_type}")

                        exec_time = result.get('execution_time', time.time() - start_time)
                        info_parts.append(f"耗时: {exec_time:.2f}s")

                        if info_parts:
                            print(f"\n执行信息: {' | '.join(info_parts)}")

                        # 显示工具调用详情
                        if result.get("tool_calls") and len(result["tool_calls"]) > 0:
                            print(f"\n🔧 工具调用详情:")
                            for i, call in enumerate(result["tool_calls"], 1):
                                status_icon = "✅" if call.get("success", True) else "❌"
                                tool_name = call.get("tool_name", "unknown")
                                print(f"  {i}. {status_icon} {tool_name}")
                                if not call.get("success", True):
                                    result_preview = str(call.get("result", ""))[:100]
                                    print(f"     错误: {result_preview}...")
                    else:
                        print(f"\n❌ 错误: {result.get('error', '未知错误')}")

                        conversation_history.append({"role": "user", "content": query})
                        conversation_history.append({
                            "role": "assistant",
                            "content": f"处理出错: {result.get('error', '未知错误')}"
                        })

                except KeyboardInterrupt:
                    print("\n\n接收到中断信号，正在退出...")
                    break
                except Exception as e:
                    print(f"❌ 处理错误: {e}")
                    import traceback
                    print(f"详细错误: {traceback.format_exc()}")

        else:
            # 单次查询模式
            optimization_enabled = not args.no_optimize
            print(f"🔍 处理查询: {args.query}")
            print(f"🧠 智能优化: {'开启' if optimization_enabled else '关闭'}")

            start_time = time.time()
            result = await client.process_query(args.query, use_optimization=optimization_enabled)

            if result["success"]:
                print(f"\n💡 回答:")
                print(result["answer"])

                exec_time = result.get('execution_time', time.time() - start_time)
                if result.get("optimization_used"):
                    opt_info = f"(🧠 {result.get('prompt_type', 'unknown')}优化, {exec_time:.2f}s)"
                    print(f"\n{opt_info}", file=sys.stderr)
                else:
                    print(f"\n(💻 标准模式, {exec_time:.2f}s)", file=sys.stderr)

                sys.exit(0)
            else:
                print(f"❌ 错误: {result.get('error', '未知错误')}", file=sys.stderr)
                sys.exit(1)

    except Exception as e:
        print(f"❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\n清理资源...")
        await client.cleanup()
        print("再见！")


def cli_main():
    """CLI入口点"""
    asyncio.run(main())


if __name__ == "__main__":
    # asyncio.run(main_test())
    cli_main()
