import json
import logging
from typing import Dict, Any, Sequence

from mcp import Tool
from mcp.types import TextContent

from mcp_for_db.server.server_dify.config import DiFyConfig
from mcp_for_db.server.common.base.base_tools import BaseHandler
from mcp_for_db.server.server_dify.tools.dify_knowledge import get_dify_tool
from mcp_for_db.server.common import DBAPromptTemplate, DatabaseKnowledgeContext
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="dify_knowledge.log")
logger.setLevel(logging.INFO)


class RetrieveKnowledge(BaseHandler):
    name = "retrieve_knowledge"
    description = "检索DiFy数据库知识库并生成RAG增强的DBA专业提示词"

    def __init__(self):
        super().__init__()
        self.prompt_generator = DBAPromptTemplate()

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "用户的数据库相关问题或查询内容"
                    },
                    "dataset_id": {
                        "type": "string",
                        "description": "知识库ID，默认使用系统配置",
                        "default": DiFyConfig().DIFY_DATASET_ID
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回的知识片段数量",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10
                    },
                    "search_method": {
                        "type": "string",
                        "description": "搜索方法，auto会自动选择最佳方法",
                        "enum": ["auto", "semantic_search", "keyword_search"],
                        "default": "auto"
                    },
                    "include_raw_results": {
                        "type": "boolean",
                        "description": "是否在最后附加原始检索结果(用于调试)",
                        "default": False
                    }
                },
                "required": ["query"]
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """检索知识库并生成RAG增强的DBA提示词"""
        try:
            # 参数验证和提取
            user_query = arguments.get("query", "").strip()
            if not user_query:
                raise ValueError("查询内容不能为空")

            dataset_id = arguments.get("dataset_id", DiFyConfig().DIFY_DATASET_ID)
            top_k = min(arguments.get("top_k", 5), 10)  # 限制最大返回数量
            search_method = arguments.get("search_method", "auto")
            include_raw_results = arguments.get("include_raw_results", False)

            logger.info(f"开始检索数据库知识库 - 用户查询: {user_query}")

            # 执行知识库检索
            retrieval_result = await self._perform_knowledge_retrieval(
                dataset_id, user_query, search_method, top_k
            )

            # 处理检索失败的情况
            if retrieval_result.get("状态") in ["知识库为空", "向量索引不可用", "检索失败"]:
                error_prompt = self._generate_error_prompt(user_query, retrieval_result)
                return [TextContent(type="text", text=error_prompt)]

            # 构建RAG上下文
            rag_context = self._build_rag_context(user_query, retrieval_result, search_method)

            # 生成RAG增强的DBA专业提示词
            enhanced_prompt = self.prompt_generator.generate_enhanced_prompt(
                user_query=user_query,
                rag_context=rag_context
            )

            # 准备返回结果
            results = [TextContent(type="text", text=enhanced_prompt)]

            # 可选：附加原始检索结果(用于调试)
            if include_raw_results:
                raw_results_text = f"\n\n---\n## 🔧 原始检索结果 (调试信息)\n```json\n{json.dumps(retrieval_result, ensure_ascii=False, indent=2)}\n```"
                results.append(TextContent(type="text", text=raw_results_text))

            logger.info(f"成功生成DBA专业提示词 - 检索片段数: {len(rag_context.retrieved_segments)}")
            return results

        except Exception as e:
            logger.error(f"生成DBA提示词时出错: {str(e)}", exc_info=True)
            error_prompt = f"""# ⚠️ 服务异常
                    抱歉，在处理您的数据库问题时遇到技术故障：
                    
                    **错误信息**: {str(e)}
                    
                    **建议操作**:
                    1. 请稍后重试
                    2. 如是复杂查询，可尝试简化问题描述
                    3. 如问题持续，请联系技术支持
                    
                    **您的原始问题**: {arguments.get('query', '未获取到查询内容')}
                    """
            return [TextContent(type="text", text=error_prompt)]

    async def _perform_knowledge_retrieval(self, dataset_id: str, query: str,
                                           search_method: str, top_k: int) -> Dict[str, Any]:
        """执行知识库检索"""
        try:
            dify_tool = get_dify_tool()

            # 检查知识库状态
            dataset_info = await dify_tool.get_dataset_info(dataset_id)
            doc_count = dataset_info.get("document_count", 0)
            embedding_available = dataset_info.get("embedding_available", False)

            if doc_count == 0:
                return {
                    "状态": "知识库为空",
                    "原因": "数据库知识库中暂无文档内容",
                    "建议": "请管理员添加相关技术文档"
                }

            # 自动选择搜索方法
            if search_method == "auto":
                search_method = "semantic_search" if embedding_available else "keyword_search"
            elif search_method == "semantic_search" and not embedding_available:
                logger.warning("语义搜索不可用，自动降级到关键词搜索")
                search_method = "keyword_search"

            # 执行检索
            result = await dify_tool.retrieve_knowledge_base(
                dataset_id=dataset_id,
                query=query,
                search_method=search_method,
                top_k=top_k,
                reranking_enable=False,
                score_threshold_enabled=False,
                auto_fallback=True
            )

            # 格式化结果
            formatted_result = {
                "查询信息": result.get("query", {}),
                "搜索方法": search_method,
                "检索结果": []
            }

            for record in result.get("records", []):
                segment = record.get("segment", {})
                document = segment.get("document", {})

                formatted_record = {
                    "分段ID": segment.get("id"),
                    "内容": segment.get("content", ""),
                    "答案": segment.get("answer"),
                    "相似度分数": record.get("score", 0),
                    "词汇数量": segment.get("word_count", 0),
                    "关键词": segment.get("keywords", []),
                    "文档信息": {
                        "文档ID": document.get("id"),
                        "文档名称": document.get("name"),
                        "数据源类型": document.get("data_source_type")
                    }
                }
                formatted_result["检索结果"].append(formatted_record)

            return formatted_result

        except Exception as e:
            logger.error(f"知识库检索失败: {str(e)}")
            return {
                "状态": "检索失败",
                "错误": str(e)
            }

    def _build_rag_context(self, query: str, retrieval_result: Dict[str, Any],
                           search_method: str) -> DatabaseKnowledgeContext:
        """构建RAG上下文"""
        retrieved_segments = retrieval_result.get("检索结果", [])

        confidence_scores = [segment.get("相似度分数", 0) for segment in retrieved_segments]

        knowledge_sources = []
        all_keywords = []

        for segment in retrieved_segments:
            # 收集文档来源
            doc_name = segment.get("文档信息", {}).get("文档名称")
            if doc_name:
                knowledge_sources.append(doc_name)

            # 收集关键词
            keywords = segment.get("关键词", [])
            if keywords:
                all_keywords.extend(keywords)

        return DatabaseKnowledgeContext(
            query=query,
            search_method=search_method,
            retrieved_segments=retrieved_segments,
            knowledge_sources=list(set(knowledge_sources)),
            confidence_scores=confidence_scores,
            keywords=list(set(all_keywords))
        )

    def _generate_error_prompt(self, user_query: str, error_result: Dict[str, Any]) -> str:
        """生成错误情况下的提示词"""
        status = error_result.get("状态", "未知错误")
        reason = error_result.get("原因", "")
        suggestion = error_result.get("建议", "")

        return f"""# 数据库专家助手
                ## ⚠️ 知识库访问异常
                
                **状态**: {status}
                **原因**: {reason}
                **建议**: {suggestion}
                
                ## 用户问题
                {user_query}
                
                ## 通用技术支持
                虽然无法获取专业知识库内容，但我仍可基于通用数据库知识为您提供帮助：
                
                ### 📋 请提供更多信息
                为了更好地帮助您解决数据库问题，请提供：
                - 具体的数据库类型和版本
                - 详细的错误信息或现象描述  
                - 相关的业务场景或使用需求
                - 当前的系统配置或数据量级
                
                ### 🔧 常见问题分类
                - **性能优化**: SQL调优、索引设计、配置调整
                - **故障处理**: 错误诊断、数据恢复、系统修复
                - **架构设计**: 选型建议、容量规划、高可用设计
                - **安全配置**: 权限管理、数据加密、访问控制
                
                请详细描述您的具体问题，我将基于通用最佳实践为您提供专业建议。
                """
