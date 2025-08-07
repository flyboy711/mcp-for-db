import json

import aiohttp
from typing import Optional

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.server_dify.config import get_current_session_config
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="dify_knowledge.log")
logger.setLevel(LOG_LEVEL)


class VectorIndexNotFoundError(Exception):
    """向量索引不存在错误"""
    pass


class DiFyAPIError(Exception):
    """DiFy API错误"""
    pass


class DiFyKnowledgeBaseTool:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def get_dataset_info(self, dataset_id: str) -> dict:
        """获取知识库详情"""
        url = f"{self.base_url}/datasets/{dataset_id}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"获取知识库详情失败: {response.status}, {await response.text()}")

    async def retrieve_knowledge_base(self, dataset_id: str, query: str,
                                      search_method: str = "semantic_search",
                                      top_k: int = 5,
                                      reranking_enable: bool = False,
                                      score_threshold_enabled: bool = False,
                                      score_threshold: Optional[float] = None,
                                      auto_fallback: bool = True) -> dict:
        """检索知识库，可自动降级：语义降为关键词查询"""
        url = f"{self.base_url}/datasets/{dataset_id}/retrieve"

        payload = {
            "query": query,
            "retrieval_model": {
                "search_method": search_method,
                "reranking_enable": reranking_enable,
                "reranking_mode": None,
                "reranking_model": {
                    "reranking_provider_name": "",
                    "reranking_model_name": ""
                },
                "weights": None,
                "top_k": top_k,
                "score_threshold_enabled": score_threshold_enabled,
                "score_threshold": score_threshold
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, json=payload) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 400:
                    error_text = await response.text()
                    error_data = json.loads(error_text) if error_text else {}
                    error_message = error_data.get("message", "")

                    # 检查是否是向量索引相关错误
                    if "collection not found" in error_message or "MilvusException" in error_message:
                        if auto_fallback and search_method == "semantic_search":
                            # 自动降级到关键词搜索
                            logger.warning(f"语义搜索失败，自动降级到关键词搜索: {error_message}")
                            return await self.retrieve_knowledge_base(
                                dataset_id=dataset_id,
                                query=query,
                                search_method="keyword_search",
                                top_k=top_k,
                                reranking_enable=False,  # 关键词搜索通常不需要重排序
                                score_threshold_enabled=False,
                                auto_fallback=False  # 避免无限递归
                            )
                        else:
                            # 返回诊断信息
                            raise VectorIndexNotFoundError(
                                f"向量索引不存在或未准备就绪。原因: {error_message}。"
                                f"建议：1) 检查知识库是否有文档 2) 检查向量索引是否已构建完成 3) 尝试使用关键词搜索"
                            )
                    else:
                        raise Exception(f"检索知识库失败: {response.status}, {error_text}")
                else:
                    raise Exception(f"检索知识库失败: {response.status}, {await response.text()}")

    async def get_document_segments(self, dataset_id: str, document_id: str,
                                    keyword: Optional[str] = None,
                                    status: str = "completed",
                                    page: int = 1,
                                    limit: int = 20) -> dict:
        """查询文档分段"""
        url = f"{self.base_url}/datasets/{dataset_id}/documents/{document_id}/segments"

        params = {
            "status": status,
            "page": str(page),
            "limit": str(limit)
        }
        if keyword:
            params["keyword"] = keyword

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"查询文档分段失败: {response.status}, {await response.text()}")

    async def get_segment_child_chunks(self, dataset_id: str, document_id: str, segment_id: str,
                                       keyword: Optional[str] = None,
                                       page: int = 1,
                                       limit: int = 20) -> dict:
        """查询文档子分段"""
        url = f"{self.base_url}/datasets/{dataset_id}/documents/{document_id}/segments/{segment_id}/child_chunks"

        params = {
            "page": str(page),
            "limit": str(limit)
        }
        if keyword:
            params["keyword"] = keyword

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"查询文档子分段失败: {response.status}, {await response.text()}")

    async def get_dataset_metadata(self, dataset_id: str) -> dict:
        """查询知识库元信息列表"""
        url = f"{self.base_url}/datasets/{dataset_id}/metadata"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise Exception(f"查询知识库元信息失败: {response.status}, {await response.text()}")


# 全局DiFy工具实例
def get_dify_tool():
    """获取DiFy工具实例"""
    dify_config = get_current_session_config()
    return DiFyKnowledgeBaseTool(
        api_key=dify_config.server_config.get("DIFY_API_KEY"),
        base_url=dify_config.server_config.get("DIFY_BASE_URL")
    )
