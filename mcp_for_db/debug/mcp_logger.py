import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List


class MCPCommunicationLogger:
    """ MCP 通信日志记录 """

    def __init__(self, log_file: str = "datas/logs/mcp_debug_io.log"):
        self.log_file = Path(__file__).parent.parent.parent.joinpath(log_file)
        self.session_id = str(uuid.uuid4())
        self.communication_sequence = 0
        self.log_file.parent.parent.parent.mkdir(parents=True, exist_ok=True)
        self._init_log_file()

    def _init_log_file(self):
        session_start = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "session_start",
            "session_id": self.session_id,
            "sequence": self._get_next_sequence(),
            "data": {"message": "MCP 通信会话开始"}
        }
        self._write_log_entry(session_start)

    def _get_next_sequence(self) -> int:
        self.communication_sequence += 1
        return self.communication_sequence

    def _write_log_entry(self, entry: Dict[str, Any]):
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"写入通信日志失败: {e}")

    def log_event(self, event_type: str, data: Dict[str, Any], server_name: str = None,
                  request_type: str = None, response_type: str = None):
        """通用日志记录方法"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "session_id": self.session_id,
            "sequence": self._get_next_sequence(),
            "data": data
        }
        if server_name:
            entry["server_name"] = server_name
        if request_type:
            entry["request_type"] = request_type
        if response_type:
            entry["response_type"] = response_type
        self._write_log_entry(entry)

    def log_tool_call(self, server_name: str, tool_name: str, arguments: Dict[str, Any],
                      result: Any = None, success: bool = True, error: str = None, execution_time: float = None):
        """记录工具调用"""
        data = {
            "tool_name": tool_name,
            "arguments": arguments,
            "success": success,
            "execution_time": execution_time
        }
        if result is not None:
            data["result"] = str(result)[:500]  # 限制结果长度
        if error:
            data["error"] = error
        self.log_event("tool_call", data, server_name)

    def log_prompt_call(self, server_name: str, prompt_name: str, arguments: Dict[str, Any],
                        result: str = None, success: bool = True, error: str = None, execution_time: float = None):
        """记录提示词调用"""
        data = {
            "prompt_name": prompt_name,
            "arguments": arguments,
            "success": success,
            "execution_time": execution_time
        }
        if result:
            data["result"] = result[:1000]  # 限制结果长度
        if error:
            data["error"] = error
        self.log_event("prompt_call", data, server_name)

    def log_llm_interaction(self, model: str, messages: List[Dict], response: Any = None,
                            success: bool = True, error: str = None, execution_time: float = None):
        """记录 LLM 交互"""
        data = {
            "model": model,
            "messages_count": len(messages),
            "success": success,
            "execution_time": execution_time
        }
        if response:
            data["response"] = str(response)[:500]  # 限制响应长度
        if error:
            data["error"] = error
        self.log_event("llm_interaction", data)

    def log_query_processing(self, query: str, result: Dict[str, Any] = None,
                             success: bool = True, error: str = None, execution_time: float = None):
        """记录查询处理"""
        data = {
            "query": query[:1000],  # 限制查询长度
            "success": success,
            "execution_time": execution_time
        }
        if result:
            data.update({
                "answer_length": len(result.get("answer", "")),
                "tool_calls_count": len(result.get("tool_calls", [])),
                "optimization_used": result.get("optimization_used", False)
            })
        if error:
            data["error"] = error
        self.log_event("query_processing", data)

    def log_session_end(self):
        """记录会话结束"""
        self.log_event("session_end", {
            "message": "MCP 通信会话结束",
            "total_sequences": self.communication_sequence
        })
