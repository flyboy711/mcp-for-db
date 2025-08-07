from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import json
import asyncio
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
import time
import uvicorn

# 导入我们的 MCP 客户端
from mcp_for_db.client.client import MCPClient
from mcp_for_db.server.shared.utils import get_logger, configure_logger

# 配置日志
logger = get_logger(__name__)
configure_logger("FastAPI.log")
logger.setLevel(logging.INFO)

# 全局变量
mcp_service = None
conversation_cache = {}  # 简单的会话缓存


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global mcp_service

    # 启动时就初始化 MCP 服务
    logger.info("🚀 正在初始化 MCP 服务...")
    try:
        mcp_service = MCPClient()
        await mcp_service.initialize()
        logger.info("✅ MCP服务初始化完成")
    except Exception as e:
        logger.error(f"❌ MCP服务初始化失败: {e}")
        raise

    yield

    # 关闭时清理资源
    logger.info("🧹 正在清理 MCP 服务...")
    if mcp_service:
        try:
            await mcp_service.cleanup()
            logger.info("✅ MCP 服务清理完成")
        except Exception as e:
            logger.error(f"❌ 清理 MCP 服务时出错: {e}")


# 创建 FastAPI 应用
app = FastAPI(
    title="MCP智能问答API",
    description="基于MCP客户端和大模型的智能问答接口，支持数据库查询和多种AI模型",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境请限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求/响应模型
class QueryRequest(BaseModel):
    question: str = Field(..., description="用户问题", min_length=1, max_length=5000)
    conversation_id: Optional[str] = Field(None, description="会话ID，用于多轮对话")
    conversation_history: Optional[List[Dict[str, str]]] = Field(None, description="对话历史")
    include_tool_info: Optional[bool] = Field(False, description="是否包含工具调用详情")
    stream: Optional[bool] = Field(False, description="是否启用流式响应")

    class Config:
        json_schema_extra = {
            "example": {
                "question": "显示所有数据库表",
                "conversation_id": "conv_12345",
                "include_tool_info": True
            }
        }


class QueryResponse(BaseModel):
    success: bool
    answer: str
    conversation_id: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    processing_time: float
    model_info: Optional[Dict[str, str]] = None
    error: Optional[str] = None
    timestamp: str

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "answer": "数据库中有以下表：users, products, orders",
                "conversation_id": "conv_12345",
                "processing_time": 1.23,
                "timestamp": "2025-08-07T18:00:00"
            }
        }


class HealthResponse(BaseModel):
    status: str
    details: Dict[str, Any]
    timestamp: str
    version: str


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    server: str


class ConversationInfo(BaseModel):
    conversation_id: str
    created_at: str
    last_updated: str
    message_count: int
    summary: Optional[str] = None


class ToolExecutionRequest(BaseModel):
    tool_name: str = Field(..., description="工具名称，格式为：ServerName_ToolName")
    tool_args: Dict[str, Any] = Field(default_factory=dict, description="工具参数")

    class Config:
        json_schema_extra = {
            "example": {
                "tool_name": "MySQLServer_show_tables",
                "tool_args": {}
            }
        }


# 辅助函数
def generate_conversation_id() -> str:
    """生成会话ID"""
    return f"conv_{uuid.uuid4().hex[:12]}_{int(time.time())}"


def get_current_timestamp() -> str:
    """获取当前时间戳"""
    return datetime.now().isoformat()


async def get_mcp_service() -> MCPClient:
    """依赖注入：获取 MCP 服务"""
    if mcp_service is None:
        raise HTTPException(
            status_code=503,
            detail="MCP 服务未初始化，请稍后重试"
        )
    return mcp_service


def manage_conversation_cache(conversation_id: str, messages: List[Dict] = None):
    """管理会话缓存"""
    current_time = get_current_timestamp()

    if conversation_id not in conversation_cache:
        conversation_cache[conversation_id] = {
            "created_at": current_time,
            "last_updated": current_time,
            "messages": [],
            "message_count": 0
        }

    if messages:
        conversation_cache[conversation_id]["messages"].extend(messages)
        conversation_cache[conversation_id]["message_count"] = len(
            conversation_cache[conversation_id]["messages"]
        )
        conversation_cache[conversation_id]["last_updated"] = current_time

    return conversation_cache[conversation_id]


# API 端点
@app.get("/", response_model=Dict[str, str])
async def root():
    """根路径 - API 信息"""
    return {
        "service": "MCP 智能问答 API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "health": "/health",
        "description": "基于 MCP 客户端和大模型的智能问答服务"
    }


@app.post("/query", response_model=QueryResponse)
async def process_query(
        request: QueryRequest,
        background_tasks: BackgroundTasks,
        service: MCPClient = Depends(get_mcp_service)
):
    """
    处理用户查询的主要接口

    这是核心接口，用户提交问题，系统调用 MCP 客户端和大模型处理后返回结果。
    支持：
    - 自然语言问题处理
    - 自动工具调用（如数据库查询）
    - 多轮对话管理
    - 性能监控
    """
    start_time = time.time()
    conversation_id = request.conversation_id or generate_conversation_id()

    try:
        logger.info(f"📝 收到查询 [会话:{conversation_id[:12]}...]: {request.question[:100]}...")

        # 获取会话历史
        conversation_history = request.conversation_history or []
        if conversation_id in conversation_cache and not conversation_history:
            # 如果没有提供历史，使用缓存的
            conversation_history = conversation_cache[conversation_id]["messages"]

        # 调用 MCP 客户端处理查询（这里会自动调用大模型和工具）
        logger.info(f"🤖 开始调用 MCP 客户端处理查询...")
        result = await service.process_query(
            user_query=request.question,
            conversation_history=conversation_history
        )

        processing_time = time.time() - start_time

        # 更新会话缓存
        new_messages = [
            {"role": "user", "content": request.question},
            {"role": "assistant", "content": result["answer"]}
        ]
        manage_conversation_cache(conversation_id, new_messages)

        # 构建响应
        response = QueryResponse(
            success=result["success"],
            answer=result["answer"],
            conversation_id=conversation_id,
            processing_time=round(processing_time, 3),
            timestamp=get_current_timestamp()
        )

        # 添加可选信息
        if request.include_tool_info and result.get("tool_calls"):
            response.tool_calls = result["tool_calls"]

        # 添加模型信息
        if hasattr(service, 'model'):
            response.model_info = {
                "model": service.model,
                "provider": service.provider.value if hasattr(service, 'provider') else "unknown"
            }

        if not result["success"]:
            response.error = result.get("error")

        # 后台任务：记录统计信息
        background_tasks.add_task(
            log_query_stats,
            conversation_id,
            request.question,
            result["success"],
            processing_time,
            len(result.get("tool_calls", []))
        )

        logger.info(f"✅ 查询处理完成 [会话:{conversation_id[:12]}...] 用时:{processing_time:.3f}s")
        return response

    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"❌ 处理查询时出错 [会话:{conversation_id[:12]}...]: {e}")
        import traceback
        logger.error(f"详细错误信息: {traceback.format_exc()}")

        return QueryResponse(
            success=False,
            answer="抱歉，处理您的问题时出现了错误，请稍后重试。如果问题持续存在，请联系管理员。",
            conversation_id=conversation_id,
            processing_time=round(processing_time, 3),
            error=str(e),
            timestamp=get_current_timestamp()
        )


@app.post("/chat/stream")
async def chat_stream(
        request: QueryRequest,
        service: MCPClient = Depends(get_mcp_service)
):
    """
    流式对话接口
    返回 Server-Sent Events 格式的流式响应
    """
    conversation_id = request.conversation_id or generate_conversation_id()

    async def generate_stream():
        try:
            logger.info(f"🌊 开始流式处理 [会话:{conversation_id[:12]}...]")

            yield f"data: {json.dumps({'type': 'start', 'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

            # 获取会话历史
            conversation_history = request.conversation_history or []
            if conversation_id in conversation_cache and not conversation_history:
                conversation_history = conversation_cache[conversation_id]["messages"]

            # 处理查询
            start_time = time.time()
            result = await service.process_query(
                user_query=request.question,
                conversation_history=conversation_history
            )
            processing_time = time.time() - start_time

            # 流式输出答案
            answer = result["answer"]

            # 如果有工具调用，先发送工具信息
            if result.get("tool_calls") and request.include_tool_info:
                tool_info = {
                    "type": "tool_calls",
                    "tools": result["tool_calls"]
                }
                yield f"data: {json.dumps(tool_info, ensure_ascii=False)}\n"

            # 模拟流式输出答案（按句子分割）
            sentences = answer.split('。')
            for i, sentence in enumerate(sentences):
                if sentence.strip():
                    chunk_data = {
                        "type": "content",
                        "content": sentence + ('。' if i < len(sentences) - 1 else ''),
                        "index": i
                    }
                    yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n"
                    await asyncio.sleep(0.1)  # 模拟延迟

            # 发送完成信号
            final_data = {
                "type": "done",
                "conversation_id": conversation_id,
                "full_answer": answer,
                "processing_time": round(processing_time, 3),
                "success": result["success"]
            }

            if request.include_tool_info and result.get("tool_calls"):
                final_data["tool_calls"] = result["tool_calls"]

            yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n"

            # 更新会话缓存
            new_messages = [
                {"role": "user", "content": request.question},
                {"role": "assistant", "content": answer}
            ]
            manage_conversation_cache(conversation_id, new_messages)

        except Exception as e:
            logger.error(f"❌ 流式处理出错: {e}")
            error_data = {
                "type": "error",
                "error": str(e),
                "conversation_id": conversation_id
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream"
        }
    )


@app.get("/tools", response_model=List[ToolInfo])
async def get_available_tools(service: MCPClient = Depends(get_mcp_service)):
    """获取所有可用的工具列表"""
    try:
        tools = service.get_available_tools()

        # 转换为更详细的格式
        tool_list = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool["function"]
                # 提取服务器名称
                server_name = func["name"].split("_")[0] if "_" in func["name"] else "unknown"

                tool_info = ToolInfo(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters=func.get("parameters", {}),
                    server=server_name
                )
                tool_list.append(tool_info)

        logger.info(f"📋 返回 {len(tool_list)} 个可用工具")
        return tool_list

    except Exception as e:
        logger.error(f"❌ 获取工具列表时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check(service: MCPClient = Depends(get_mcp_service)):
    """健康检查接口"""
    try:
        health_status = await service.health_check()

        status = "healthy" if health_status.get("initialized", False) else "unhealthy"

        # 添加更多系统信息
        enhanced_details = {
            **health_status,
            "conversation_cache_size": len(conversation_cache),
            "active_conversations": len([
                conv for conv in conversation_cache.values()
                if (datetime.now() - datetime.fromisoformat(conv["last_updated"])).seconds < 3600
            ]),
            "api_version": "1.0.0"
        }

        return HealthResponse(
            status=status,
            details=enhanced_details,
            timestamp=get_current_timestamp(),
            version="1.0.0"
        )

    except Exception as e:
        logger.error(f"❌ 健康检查时出错: {e}")
        return HealthResponse(
            status="error",
            details={"error": str(e)},
            timestamp=get_current_timestamp(),
            version="1.0.0"
        )


@app.get("/conversations", response_model=List[ConversationInfo])
async def get_conversations():
    """获取所有会话信息"""
    conversations = []

    for conv_id, conv_data in conversation_cache.items():
        # 生成会话摘要（取第一个用户消息）
        summary = None
        if conv_data["messages"]:
            for msg in conv_data["messages"]:
                if msg.get("role") == "user":
                    summary = msg["content"][:50] + "..." if len(msg["content"]) > 50 else msg["content"]
                    break

        conversation = ConversationInfo(
            conversation_id=conv_id,
            created_at=conv_data["created_at"],
            last_updated=conv_data["last_updated"],
            message_count=conv_data["message_count"],
            summary=summary
        )
        conversations.append(conversation)

    # 按最后更新时间排序
    conversations.sort(key=lambda x: x.last_updated, reverse=True)
    return conversations


@app.get("/conversations/{conversation_id}")
async def get_conversation_history(conversation_id: str):
    """获取特定会话的历史记录"""
    if conversation_id not in conversation_cache:
        raise HTTPException(status_code=404, detail="会话不存在")

    conversation_data = conversation_cache[conversation_id]
    return {
        "conversation_id": conversation_id,
        "messages": conversation_data["messages"],
        "metadata": {
            "created_at": conversation_data["created_at"],
            "last_updated": conversation_data["last_updated"],
            "message_count": conversation_data["message_count"]
        }
    }


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除指定会话"""
    if conversation_id not in conversation_cache:
        raise HTTPException(status_code=404, detail="会话不存在")

    del conversation_cache[conversation_id]
    logger.info(f"🗑️ 删除会话: {conversation_id}")
    return {"message": f"会话 {conversation_id} 已删除", "timestamp": get_current_timestamp()}


@app.post("/tools/execute")
async def execute_tool_directly(
        request: ToolExecutionRequest,
        service: MCPClient = Depends(get_mcp_service)
):
    """直接执行指定工具"""
    try:
        logger.info(f"🔧 直接执行工具: {request.tool_name}")

        start_time = time.time()
        result = await service.call_mcp_tool(request.tool_name, request.tool_args)
        processing_time = time.time() - start_time

        return {
            "success": True,
            "tool_name": request.tool_name,
            "arguments": request.tool_args,
            "result": result,
            "processing_time": round(processing_time, 3),
            "timestamp": get_current_timestamp()
        }

    except Exception as e:
        logger.error(f"❌ 执行工具失败: {e}")
        return {
            "success": False,
            "tool_name": request.tool_name,
            "arguments": request.tool_args,
            "error": str(e),
            "timestamp": get_current_timestamp()
        }


# 后台任务函数
async def log_query_stats(
        conversation_id: str,
        question: str,
        success: bool,
        processing_time: float,
        tool_calls_count: int
):
    """记录查询统计信息"""
    logger.info(
        f"📊 查询统计 - 会话:{conversation_id[:12]}... | "
        f"成功:{success} | 用时:{processing_time:.3f}s | "
        f"问题长度:{len(question)} | 工具调用:{tool_calls_count}"
    )


# 异常处理器
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logger.warning(f"HTTP异常: {exc.status_code} - {exc.detail}")
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "timestamp": get_current_timestamp()
    }


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"❌ 未处理的异常: {exc}")
    import traceback
    logger.error(f"详细错误信息: {traceback.format_exc()}")
    return {
        "error": "服务器内部错误，请稍后重试",
        "timestamp": get_current_timestamp(),
        "status_code": 500
    }


def main():
    """命令行启动函数"""
    import argparse
    parser = argparse.ArgumentParser(description="MCP API Server")
    parser.add_argument("--host", default="0.0.0.0", help="服务器地址")
    parser.add_argument("--port", type=int, default=8000, help="服务器端口")
    parser.add_argument("--reload", action="store_true", help="启用热重载")

    args = parser.parse_args()

    logger.info(f"🚀 启动 MCP 智能问答 API 服务...")
    logger.info(f"📍 服务地址: http://{args.host}:{args.port}")
    logger.info(f"📖 API文档: http://{args.host}:{args.port}/docs")

    uvicorn.run(
        "mcp_for_db.client.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    main()
