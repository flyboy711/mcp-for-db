import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from contextlib import AsyncExitStack

from openai import OpenAI
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv(os.path.join(Path(__file__).parent.parent.parent, ".env"))


class MCPClient:
    """封装MCP客户端，用于处理用户查询"""

    def __init__(self, servers_config: Dict[str, str] = None):
        """
        初始化MCP客户端服务

        Args:
            servers_config: 服务器配置，形如 {"weather": "weather_server.py"}
        """
        self.exit_stack = AsyncExitStack()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.model = os.getenv("MODEL")

        if not self.openai_api_key:
            raise ValueError("❌ 未找到 OPENAI_API_KEY，请在 .env 文件中配置")

        # 初始化 OpenAI Client
        self.client = OpenAI(api_key=self.openai_api_key, base_url=self.base_url)

        # 存储服务器会话和工具信息
        self.sessions: Dict[str, ClientSession] = {}
        self.tools_by_session: Dict[str, list] = {}
        self.all_tools = []

        # 默认服务器配置
        self.servers_config = servers_config or {
            "SQLServer": "mysql_server.py",
            "DiFyServer": "dify_server.py"
        }

        self._is_initialized = False
        self.logger = logging.getLogger(__name__)

    async def initialize(self):
        """初始化所有MCP服务器连接"""
        if self._is_initialized:
            return

        try:
            await self.connect_to_servers(self.servers_config)
            self._is_initialized = True
            self.logger.info("MCP服务初始化完成")
        except Exception as e:
            self.logger.error(f"MCP服务初始化失败: {e}")
            raise

    async def connect_to_servers(self, servers: dict):
        """连接到多个MCP服务器"""
        for server_name, script_path in servers.items():
            try:
                session = await self._start_one_server(script_path)
                self.sessions[server_name] = session

                # 获取工具列表
                resp = await session.list_tools()
                self.tools_by_session[server_name] = resp.tools

                for tool in resp.tools:
                    function_name = f"{server_name}_{tool.name}"
                    self.all_tools.append({
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "description": tool.description,
                            "input_schema": tool.inputSchema
                        }
                    })
            except Exception as e:
                self.logger.error(f"连接服务器 {server_name} 失败: {e}")
                continue

        # 转换工具格式
        self.all_tools = await self.transform_json(self.all_tools)
        self.logger.info(f"已连接 {len(servers)} 个服务器，加载 {len(self.all_tools)} 个工具")

    async def _start_one_server(self, script_path: str) -> ClientSession:
        """启动单个MCP服务器"""
        is_python = script_path.endswith(".py")
        is_js = script_path.endswith(".js")
        if not (is_python or is_js):
            raise ValueError("服务器脚本必须是 .py 或 .js 文件")

        command = "python" if is_python else "node"
        server_params = StdioServerParameters(
            command=command,
            args=[script_path],
            env=None
        )
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport
        session = await self.exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session

    async def transform_json(self, json_data):
        """转换工具格式为OpenAI Function Calling格式"""
        result = []

        for item in json_data:
            if not isinstance(item, dict) or "type" not in item or "function" not in item:
                continue

            old_func = item["function"]
            if not isinstance(old_func, dict) or "name" not in old_func or "description" not in old_func:
                continue

            new_func = {
                "name": old_func["name"],
                "description": old_func["description"],
                "parameters": {}
            }

            if "input_schema" in old_func and isinstance(old_func["input_schema"], dict):
                old_schema = old_func["input_schema"]
                new_func["parameters"]["type"] = old_schema.get("type", "object")
                new_func["parameters"]["properties"] = old_schema.get("properties", {})
                new_func["parameters"]["required"] = old_schema.get("required", [])

            result.append({
                "type": item["type"],
                "function": new_func
            })

        return result

    async def process_query(self, user_query: str, conversation_history: List[Dict] = None) -> Dict[str, Any]:
        """
        处理用户查询的核心方法

        Args:
            user_query: 用户问题
            conversation_history: 对话历史 (可选)

        Returns:
            处理结果字典，包含回答、工具调用信息等
        """
        if not self._is_initialized:
            await self.initialize()

        # 构建消息历史
        messages = conversation_history or []
        messages.append({"role": "user", "content": user_query})

        try:
            # 调用大模型处理
            response = await self._chat_with_tools(messages)

            return {
                "success": True,
                "answer": response["answer"],
                "tool_calls": response.get("tool_calls", []),
                "messages": response["messages"]
            }

        except Exception as e:
            self.logger.error(f"处理查询失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "answer": "抱歉，处理您的问题时出现了错误。"
            }

    async def _chat_with_tools(self, messages: List[Dict]) -> Dict[str, Any]:
        """使用工具的对话处理"""
        tool_calls_info = []

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=self.all_tools
        )

        # 处理工具调用
        if response.choices[0].finish_reason == "tool_calls":
            while True:
                messages, tool_call_info = await self._handle_tool_calls(messages, response)
                tool_calls_info.extend(tool_call_info)

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=self.all_tools
                )

                if response.choices[0].finish_reason != "tool_calls":
                    break

        return {
            "answer": response.choices[0].message.content,
            "tool_calls": tool_calls_info,
            "messages": messages
        }

    async def _handle_tool_calls(self, messages: List[Dict], response) -> tuple:
        """处理工具调用"""
        tool_calls = response.choices[0].message.tool_calls
        messages.append(response.choices[0].message.model_dump())
        tool_calls_info = []

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # 记录工具调用信息
            tool_call_record = {
                "tool_name": tool_name,
                "arguments": tool_args,
                "call_id": tool_call.id
            }

            try:
                # 执行MCP工具
                result = await self._call_mcp_tool(tool_name, tool_args)
                tool_call_record["result"] = result
                tool_call_record["success"] = True

            except Exception as e:
                result = f"工具调用失败: {str(e)}"
                tool_call_record["result"] = result
                tool_call_record["success"] = False
                self.logger.error(f"工具调用失败: {tool_name}, 错误: {e}")

            tool_calls_info.append(tool_call_record)

            # 添加工具结果到消息历史
            messages.append({
                "role": "tool",
                "content": result,
                "tool_call_id": tool_call.id,
            })

        return messages, tool_calls_info

    async def _call_mcp_tool(self, tool_full_name: str, tool_args: dict) -> str:
        """调用MCP工具"""
        parts = tool_full_name.split("_", 1)
        if len(parts) != 2:
            return f"无效的工具名称: {tool_full_name}"

        server_name, tool_name = parts
        session = self.sessions.get(server_name)
        if not session:
            return f"找不到服务器: {server_name}"

        try:
            resp = await session.call_tool(tool_name, tool_args)
            return resp.content if resp.content else "工具执行无输出"
        except Exception as e:
            raise Exception(f"调用工具 {tool_name} 失败: {str(e)}")

    async def cleanup(self):
        """清理资源"""
        await self.exit_stack.aclose()
        self._is_initialized = False

    def get_available_tools(self) -> List[Dict]:
        """获取可用工具列表"""
        return self.all_tools

    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        status = {
            "initialized": self._is_initialized,
            "servers": {},
            "total_tools": len(self.all_tools)
        }

        for server_name, session in self.sessions.items():
            try:
                # 简单的连接测试
                await session.list_tools()
                status["servers"][server_name] = "healthy"
            except Exception as e:
                status["servers"][server_name] = f"error: {str(e)}"

        return status
