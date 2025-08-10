import contextvars
from typing import Optional
from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.server_dify.config import DiFySessionConfig
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger("mcp_session_config.log")
logger.setLevel(LOG_LEVEL)

# 定义上下文变量
current_session_config = contextvars.ContextVar("session_config")


class RequestContext:
    """异步请求上下文管理器"""

    def __init__(self, session_config: DiFySessionConfig):
        self.session_config = session_config
        self._session_token = None

    async def __aenter__(self):
        """进入异步上下文"""
        self._session_token = current_session_config.set(self.session_config)
        logger.debug("请求上下文设置完成")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出异步上下文，确保资源释放"""
        if self._session_token:
            current_session_config.reset(self._session_token)
        self._session_token = None
        logger.debug("请求上下文已重置")


def get_current_session_config() -> Optional[DiFySessionConfig]:
    """获取当前请求的会话配置"""
    try:
        return current_session_config.get(None)
    except LookupError:
        return None
