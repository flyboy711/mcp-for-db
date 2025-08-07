import json
import queue
import time
import logging
import threading
import os
from urllib.parse import urlparse
from typing import List, Dict
from pydantic.networks import AnyUrl
from mcp.types import Resource
from mcp_for_db.server.common.base import BaseResource, ResourceRegistry
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="resources.log")
logger.setLevel(logging.WARNING)

# 全局查询日志存储目录
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_dir))))

QUERY_LOGS_DIR = os.path.join(root_dir, "datas", "files", "query_logs")

# 确保日志目录存在
os.makedirs(QUERY_LOGS_DIR, exist_ok=True)


class QueryLogResource(BaseResource):
    """代表具体查询资源的类"""
    auto_register: bool = False
    # 日志缓存和刷新机制
    _log_queue = queue.Queue()
    _flush_thread = None
    _running = True
    _flush_lock = threading.Lock()

    def __init__(self, operator: str, limit: str, description: str):
        super().__init__()
        self.name = f"{operator}的查询日志"
        self.uri = AnyUrl(f"logs://{operator}/{limit}")
        self.description = description
        self.mimeType = "application/json"

    @staticmethod
    def get_log_file_path(tool_name: str) -> str:
        """获取指定工具的日志文件路径"""
        # 清理工具名称，只保留字母数字和下划线
        safe_tool_name = ''.join(c for c in tool_name if c.isalnum() or c == '_')
        return os.path.join(QUERY_LOGS_DIR, f"{safe_tool_name}.json")

    @staticmethod
    def start_flush_thread():
        """启动日志刷新线程"""
        if QueryLogResource._flush_thread is None:
            QueryLogResource._running = True
            QueryLogResource._flush_thread = threading.Thread(
                target=QueryLogResource._flush_worker,
                daemon=True
            )
            QueryLogResource._flush_thread.start()
            logger.info("启动日志刷新线程")

    @staticmethod
    def stop_flush_thread():
        """停止日志刷新线程"""
        QueryLogResource._running = False
        if QueryLogResource._flush_thread:
            QueryLogResource._flush_thread.join(timeout=5)
            QueryLogResource._flush_thread = None
            logger.info("停止日志刷新线程")

    @staticmethod
    def _flush_worker():
        """日志刷新工作线程"""
        while QueryLogResource._running or not QueryLogResource._log_queue.empty():
            try:
                # 从队列中获取日志条目
                try:
                    tool_name, log_entry = QueryLogResource._log_queue.get(timeout=1)
                except queue.Empty:
                    continue

                # 获取文件路径
                file_path = QueryLogResource.get_log_file_path(tool_name)

                # 使用锁确保线程安全
                with QueryLogResource._flush_lock:
                    # 如果文件不存在，创建新文件并初始化为空数组
                    if not os.path.exists(file_path):
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump([], f)
                        logger.info(f"创建新的日志文件: {file_path}")

                    # 读取现有日志
                    logs = []
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            # 检查文件是否为空
                            if os.path.getsize(file_path) > 0:
                                try:
                                    logs = json.load(f)
                                except json.JSONDecodeError:
                                    logger.error(f"日志文件 {file_path} 格式错误，将重置文件")
                                    logs = []
                    except Exception as e:
                        logger.error(f"读取日志文件失败: {str(e)}")
                        continue

                    # 添加新日志
                    logs.append(log_entry)

                    # 写入文件
                    try:
                        # 使用临时文件写入，避免写入过程中出错导致文件损坏
                        temp_path = file_path + ".tmp"
                        with open(temp_path, 'w', encoding='utf-8') as f:
                            json.dump(logs, f, ensure_ascii=False, indent=4)

                        # 原子操作：重命名临时文件为正式文件
                        os.replace(temp_path, file_path)
                        logger.debug(f"追加日志到 {file_path}")
                    except Exception as e:
                        logger.error(f"写入日志文件失败: {str(e)}")

                # 标记任务完成
                QueryLogResource._log_queue.task_done()
            except Exception as e:
                logger.error(f"日志刷新线程出错: {str(e)}")

    @staticmethod
    def load_logs(tool_name: str) -> List[Dict]:
        """从JSON文件加载指定工具的查询日志"""
        file_path = QueryLogResource.get_log_file_path(tool_name)
        try:
            if os.path.exists(file_path):
                # 检查文件是否为空
                if os.path.getsize(file_path) == 0:
                    logger.warning(f"日志文件 {file_path} 为空")
                    return []

                with open(file_path, 'r', encoding='utf-8') as json_file:
                    try:
                        logs = json.load(json_file)
                    except json.JSONDecodeError as e:
                        logger.error(f"日志文件 {file_path} 格式错误: {str(e)}")
                        # 尝试读取原始内容
                        json_file.seek(0)
                        raw_content = json_file.read()
                        logger.debug(f"日志文件原始内容: {raw_content[:200]}...")
                        return []

                logger.info(f"从 {file_path} 加载了 {len(logs)} 条查询日志")
                return logs
            else:
                logger.info(f"日志文件 {file_path} 不存在")
                return []
        except Exception as e:
            logger.error(f"加载查询日志失败: {str(e)}")
            return []

    @staticmethod
    def log_query(tool_name: str, operation: str, ret: str = " ", success: bool = True, error: str = None):
        """记录查询日志（优化版）"""
        # 确保刷新线程已启动
        if QueryLogResource._flush_thread is None:
            QueryLogResource.start_flush_thread()

        # 创建日志条目
        log_entry = {
            "timestamp": time.time(),
            "tool_name": tool_name,
            "operation": operation,
            "result": ret,
            "success": success,
            "error_msg": error
        }

        # 将日志条目添加到队列
        QueryLogResource._log_queue.put((tool_name, log_entry))
        logger.debug(f"添加日志到队列: {tool_name} - {operation[:50]}...")

    async def get_resource_descriptions(self) -> List[Resource]:
        """返回工具SQL日志资源的描述:已返回"""
        return []

    async def read_resource(self, uri: AnyUrl) -> str:
        """读取资源内容"""
        try:
            # 解析URI格式: logs://{operator}/{limit}
            parsed = urlparse(str(uri))

            # 提取operator和limit
            path_parts = parsed.path.strip('/').split('/')
            operator = path_parts[0] if len(path_parts) > 0 else "sql_executor"
            limit_str = path_parts[1] if len(path_parts) > 1 else "50"

            # 转换limit为整数
            try:
                limit = int(limit_str)
                if limit <= 0:
                    return json.dumps({
                        "success": False,
                        "error": "Limit must be a positive integer"
                    })
            except ValueError:
                return json.dumps({
                    "success": False,
                    "error": "Invalid limit value"
                })

            # 加载该操作者的日志
            logs = self.load_logs(operator)

            # 限制返回数量
            logs = logs[-limit:] if limit < len(logs) else logs

            # 转换时间戳为可读格式
            formatted_logs = []
            for log in logs:
                formatted_log = log.copy()
                formatted_log["timestamp"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(log["timestamp"])
                )
                formatted_logs.append(formatted_log)

            return json.dumps({
                "success": True,
                "operator": operator,
                "limit": limit,
                "logs": formatted_logs,
                "total_queries": len(logs)
            })
        except Exception as e:
            logger.error(f"读取查询日志失败: {str(e)}")
            return json.dumps({
                "success": False,
                "error": str(e)
            })


class QueryLogsResource(BaseResource):
    """SQL查询日志资源"""
    name = "SQL查询日志"
    uri = AnyUrl("logs://")
    description = "提供对SQL查询日志的访问"
    mimeType = "application/json"
    auto_register = True

    def __init__(self):
        super().__init__()

    async def get_resource_descriptions(self) -> List[Resource]:
        """获取所有日志资源的描述"""
        resources = []

        # 遍历日志目录中的所有文件
        for filename in os.listdir(QUERY_LOGS_DIR):
            if filename.endswith(".json"):
                operator = filename[:-5]  # 去掉.json后缀
                # 创建资源描述
                des = f"{operator}操作产生的历史查询记录"
                resource_desc = QueryLogResource(operator, "30", des)
                ResourceRegistry.register_instance(resource_desc)

                resource_desc = Resource(
                    uri=resource_desc.uri,
                    name=resource_desc.name,
                    description=resource_desc.description,
                    mimeType=resource_desc.mimeType
                )

                resources.append(resource_desc)

        return resources

    async def read_resource(self, uri: AnyUrl) -> str:
        """读取根资源内容"""
        return json.dumps({
            "name": self.name,
            "uri": self.uri,
            "description": self.description,
            "total_log_files": len(os.listdir(QUERY_LOGS_DIR))
        })
