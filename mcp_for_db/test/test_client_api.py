import requests
import json


# 基本查询
def test_query():
    url = "http://localhost:8000/query"
    data = {
        "question": "今天北京的天气怎么样？",
        "include_tool_info": True
    }

    response = requests.post(url, json=data)
    result = response.json()

    print("回答:", result["answer"])
    if result.get("tool_calls"):
        print("工具调用:", json.dumps(result["tool_calls"], ensure_ascii=False, indent=2))


# 带对话历史的查询
def test_conversation():
    url = "http://localhost:8000/query"
    data = {
        "question": "那明天呢？",
        "conversation_history": [
            {"role": "user", "content": "今天北京天气怎么样？"},
            {"role": "assistant", "content": "今天北京天气晴朗，温度25度..."}
        ],
        "include_tool_info": False
    }

    response = requests.post(url, json=data)
    result = response.json()
    print("回答:", result["answer"])


# 获取可用工具
def test_tools():
    url = "http://localhost:8000/tools"
    response = requests.get(url)
    tools = response.json()

    print("可用工具:")
    for tool in tools:
        print(f"- {tool['function']['name']}: {tool['function']['description']}")


# 健康检查
def test_health():
    url = "http://localhost:8000/health"
    response = requests.get(url)
    health = response.json()

    print("服务状态:", health["status"])
    print("详细信息:", json.dumps(health["details"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    test_health()
    test_tools()
    test_query()
