import contextvars
from typing import Optional
from server.config import SessionConfigManager, DatabaseManager

# 定义上下文变量
current_session_config = contextvars.ContextVar("session_config")
current_database_manager = contextvars.ContextVar("database_manager")


class RequestContext:
    """请求上下文管理器"""

    def __init__(self, session_config: SessionConfigManager, db_manager: DatabaseManager):
        self.session_config = session_config
        self.db_manager = db_manager
        self._session_token = None
        self._db_token = None

    def __enter__(self):
        """进入上下文"""
        self._session_token = current_session_config.set(self.session_config)
        self._db_token = current_database_manager.set(self.db_manager)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文"""
        current_session_config.reset(self._session_token)
        current_database_manager.reset(self._db_token)
        self._session_token = None
        self._db_token = None


def get_current_session_config() -> Optional[SessionConfigManager]:
    """获取当前请求的会话配置"""
    return current_session_config.get(None)


def get_current_database_manager() -> Optional[DatabaseManager]:
    """获取当前请求的数据库管理器"""
    return current_database_manager.get(None)
