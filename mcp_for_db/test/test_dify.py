import asyncio

from mcp_for_db.server.server_dify.config import DiFyConfig
from mcp_for_db.server.server_dify.tools import RetrieveKnowledge, DiagnoseKnowledge


async def test_dify_tools():
    """测试DiFy工具"""
    try:
        print("=== 知识库诊断 ===")
        diagnose_tool = DiagnoseKnowledge()
        result = await diagnose_tool.run_tool({
            "dataset_id": DiFyConfig().DIFY_DATASET_ID
        })
        print_result("知识库诊断", result)

        print("=== 测试智能检索 (自动降级) ===")
        retrieve_tool = RetrieveKnowledge()
        result = await retrieve_tool.run_tool({
            "dataset_id": DiFyConfig().DIFY_DATASET_ID,
            "query": "OcaseBase",
            "search_method": "auto",  # 使用自动模式
            "top_k": 3,
            "auto_fallback": True
        })
        print_result("智能检索", result)

        print("=== 测试关键词搜索 ===")
        result = await retrieve_tool.run_tool({
            "dataset_id": DiFyConfig().DIFY_DATASET_ID,
            "query": "OcaseBase",
            "search_method": "keyword_search",
            "top_k": 2
        })
        print_result("关键词搜索", result)

        print("=== 测试语义搜索 ===")
        result = await retrieve_tool.run_tool({
            "dataset_id": DiFyConfig().DIFY_DATASET_ID,
            "query": "OcaseBase架构原理是什么？",
            "search_method": "semantic_search",
            "auto_fallback": False,  # 不使用降级
            "top_k": 2
        })
        print_result("语义搜索(无降级)", result)

    except Exception as e:
        print(f"测试过程中出错: {str(e)}")


def print_result(test_name: str, result):
    """格式化打印测试结果"""
    print(f"\n=== {test_name} ===")
    if isinstance(result, list) and result:
        for item in result:
            if hasattr(item, 'text'):
                print(item.text)
            else:
                print(item)
    else:
        print(result)
    print("-" * 50)


if __name__ == "__main__":
    asyncio.run(test_dify_tools())
