import contextvars
from typing import Optional
from server.config import SessionConfigManager, DatabaseManager
import logging

# 获取日志器
logger = logging.getLogger(__name__)

# 定义上下文变量
current_session_config = contextvars.ContextVar("session_config")
current_database_manager = contextvars.ContextVar("database_manager")


class RequestContext:
    """异步请求上下文管理器"""

    def __init__(self, session_config: SessionConfigManager, db_manager: DatabaseManager):
        self.session_config = session_config
        self.db_manager = db_manager
        self._session_token = None
        self._db_token = None

    async def __aenter__(self):
        """进入异步上下文"""
        # 设置当前请求的配置和数据库管理器
        self._session_token = current_session_config.set(self.session_config)
        self._db_token = current_database_manager.set(self.db_manager)
        logger.debug("请求上下文设置完成")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出异步上下文，确保资源释放"""
        # 重置上下文
        if self._session_token:
            current_session_config.reset(self._session_token)
        if self._db_token:
            current_database_manager.reset(self._db_token)
        self._session_token = None
        self._db_token = None
        logger.debug("请求上下文已重置")


def get_current_session_config() -> Optional[SessionConfigManager]:
    """获取当前请求的会话配置"""
    try:
        return current_session_config.get(None)
    except LookupError:
        return None


def get_current_database_manager() -> Optional[DatabaseManager]:
    """获取当前请求的数据库管理器"""
    try:
        return current_database_manager.get(None)
    except LookupError:
        return None
