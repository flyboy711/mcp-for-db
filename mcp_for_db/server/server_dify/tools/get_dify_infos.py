import json
import logging
from typing import Dict, Any, Sequence

from mcp import Tool
from mcp.types import TextContent

from mcp_for_db.server.server_dify.config import get_current_session_config
from mcp_for_db.server.common.base import BaseHandler
from mcp_for_db.server.server_dify.tools.dify_knowledge import get_dify_tool
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="dify_knowledge.log")
logger.setLevel(logging.WARNING)


class DiagnoseKnowledge(BaseHandler):
    name = "diagnose_knowledge"
    description = "诊断DiFy知识库状态，检查文档和配置信息"

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=self.description,
            inputSchema={
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "string",
                        "description": "知识库ID",
                        "default": get_current_session_config().server_config.get("DIFY_DATASET_ID")
                    }
                },
                "required": []
            }
        )

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """诊断知识库状态"""
        try:
            dataset_id = arguments.get("dataset_id", get_current_session_config().server_config.get("DIFY_DATASET_ID"))
            dify_tool = get_dify_tool()

            logger.info(f"诊断知识库: {dataset_id}")

            # 获取知识库基本信息
            dataset_info = await dify_tool.get_dataset_info(dataset_id)

            # 诊断结果
            diagnosis = {
                "知识库ID": dataset_id,
                "基本状态": {
                    "名称": dataset_info.get("name"),
                    "文档数量": dataset_info.get("document_count", 0),
                    "词汇数量": dataset_info.get("word_count", 0),
                    "应用数量": dataset_info.get("app_count", 0),
                    "权限": dataset_info.get("permission")
                },
                "索引状态": {
                    "索引技术": dataset_info.get("indexing_technique"),
                    "嵌入模型": dataset_info.get("embedding_model"),
                    "嵌入模型提供商": dataset_info.get("embedding_model_provider"),
                    "嵌入可用性": dataset_info.get("embedding_available", False)
                },
                "检索配置": dataset_info.get("retrieval_model_dict", {}),
                "诊断建议": []
            }

            # 生成诊断建议
            doc_count = dataset_info.get("document_count", 0)
            word_count = dataset_info.get("word_count", 0)
            embedding_available = dataset_info.get("embedding_available", False)

            if doc_count == 0:
                diagnosis["诊断建议"].append("知识库为空，请添加文档")
            elif doc_count < 5:
                diagnosis["诊断建议"].append("文档数量较少，可能影响检索效果")
            else:
                diagnosis["诊断建议"].append("文档数量充足")

            if word_count == 0:
                diagnosis["诊断建议"].append("无有效内容，请检查文档质量")
            else:
                diagnosis["诊断建议"].append(f"内容充足 ({word_count} 词汇)")

            if not embedding_available:
                diagnosis["诊断建议"].append("向量嵌入不可用，语义搜索可能失败，建议使用关键词搜索")
            else:
                diagnosis["诊断建议"].append("向量嵌入可用，支持语义搜索")

            # 测试简单检索
            try:
                test_result = await self._test_retrieval(dify_tool, dataset_id)
                diagnosis["检索测试"] = test_result
            except Exception as e:
                diagnosis["检索测试"] = {"error": str(e)}

            return [TextContent(
                type="text",
                text=json.dumps(diagnosis, ensure_ascii=False, indent=2)
            )]

        except Exception as e:
            logger.error(f"诊断知识库时出错: {str(e)}", exc_info=True)
            return [TextContent(type="text", text=f"诊断失败: {str(e)}")]

    async def _test_retrieval(self, dify_tool, dataset_id: str) -> dict:
        """测试检索功能"""
        test_results = {}

        # 测试关键词搜索
        try:
            result = await dify_tool.retrieve_knowledge_base(
                dataset_id=dataset_id,
                query="测试",
                search_method="keyword_search",
                top_k=1,
                auto_fallback=False
            )
            test_results["关键词搜索"] = f"成功 (返回 {len(result.get('records', []))} 条结果)"
        except Exception as e:
            test_results["关键词搜索"] = f"失败: {str(e)}"

        # 测试语义搜索
        try:
            result = await dify_tool.retrieve_knowledge_base(
                dataset_id=dataset_id,
                query="测试",
                search_method="semantic_search",
                top_k=1,
                auto_fallback=False
            )
            test_results["语义搜索"] = f"成功 (返回 {len(result.get('records', []))} 条结果)"
        except Exception as e:
            test_results["语义搜索"] = f"失败: {str(e)}"

        return test_results
