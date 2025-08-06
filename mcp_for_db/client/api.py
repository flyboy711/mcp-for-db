from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging
from contextlib import asynccontextmanager

from mcp_for_db.client import MCPClient

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局MCP服务实例
mcp_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global mcp_service

    # 启动时初始化MCP服务
    logger.info("正在初始化MCP服务...")
    mcp_service = MCPClient()
    try:
        await mcp_service.initialize()
        logger.info("MCP服务初始化完成")
    except Exception as e:
        logger.error(f"MCP服务初始化失败: {e}")
        raise

    yield

    # 关闭时清理资源
    logger.info("正在清理MCP服务...")
    if mcp_service:
        await mcp_service.cleanup()
    logger.info("MCP服务清理完成")


# 创建FastAPI应用
app = FastAPI(
    title="MCP智能问答API",
    description="基于MCP客户端和大模型的智能问答接口",
    version="1.0.0",
    lifespan=lifespan
)


# 请求模型
class QueryRequest(BaseModel):
    question: str
    conversation_history: Optional[List[Dict[str, str]]] = None
    include_tool_info: Optional[bool] = False


class QueryResponse(BaseModel):
    success: bool
    answer: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    conversation_id: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    details: Dict[str, Any]


# 依赖注入：获取MCP服务
async def get_mcp_service() -> MCPClient:
    if mcp_service is None:
        raise HTTPException(status_code=503, detail="MCP服务未初始化")
    return mcp_service


@app.get("/", response_model=Dict[str, str])
async def root():
    """根路径"""
    return {"message": "MCP智能问答API", "status": "running"}


@app.post("/query", response_model=QueryResponse)
async def process_query(
        request: QueryRequest,
        service: MCPClient = Depends(get_mcp_service)
):
    """
    处理用户查询的主要接口

    - **question**: 用户问题
    - **conversation_history**: 对话历史（可选）
    - **include_tool_info**: 是否在响应中包含工具调用详情
    """
    try:
        logger.info(f"收到查询: {request.question}")

        # 处理查询
        result = await service.process_query(
            user_query=request.question,
            conversation_history=request.conversation_history
        )

        response = QueryResponse(
            success=result["success"],
            answer=result["answer"]
        )

        # 根据请求决定是否包含工具调用信息
        if request.include_tool_info and "tool_calls" in result:
            response.tool_calls = result["tool_calls"]

        if not result["success"]:
            response.error = result.get("error")

        logger.info(f"查询处理完成，成功: {result['success']}")
        return response

    except Exception as e:
        logger.error(f"处理查询时出错: {e}")
        raise HTTPException(status_code=500, detail=f"处理查询时出错: {str(e)}")


@app.get("/tools", response_model=List[Dict[str, Any]])
async def get_available_tools(service: MCPClient = Depends(get_mcp_service)):
    """获取所有可用的工具列表"""
    try:
        tools = service.get_available_tools()
        return tools
    except Exception as e:
        logger.error(f"获取工具列表时出错: {e}")
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check(service: MCPClient = Depends(get_mcp_service)):
    """健康检查接口"""
    try:
        health_status = await service.health_check()

        status = "healthy" if health_status["initialized"] else "unhealthy"

        return HealthResponse(
            status=status,
            details=health_status
        )
    except Exception as e:
        logger.error(f"健康检查时出错: {e}")
        return HealthResponse(
            status="error",
            details={"error": str(e)}
        )


@app.post("/chat", response_model=QueryResponse)
async def chat_endpoint(
        request: QueryRequest,
        service: MCPClient = Depends(get_mcp_service)
):
    """
    对话接口（process_query的别名）
    """
    return await process_query(request, service)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
