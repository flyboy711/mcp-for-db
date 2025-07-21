import logging
from typing import Tuple
from server.config import SessionConfigManager
from server.security.sql_parser import SQLParser
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_security.log")
logger.setLevel(logging.WARNING)


class QueryLimiter:
    """查询安全检查器，基于会话配置进行安全检查"""

    def __init__(self, session_config: SessionConfigManager):
        """
        初始化查询安全检查器

        Args:
            session_config: 会话配置管理器实例
        """
        self.session_config = session_config
        # 创建 SQL 解析器实例
        self.sql_parser = SQLParser(session_config)

        # 获取安全配置（不使用前缀）
        self.enable_check = session_config.get('ENABLE_QUERY_CHECK', True)
        self.max_sql_length = session_config.get('MAX_SQL_LENGTH', 1000)

    def check_query(self, sql_query: str) -> Tuple[bool, str]:
        """
        检查SQL查询是否安全，基于会话配置

        Args:
            sql_query: SQL查询语句

        Returns:
            Tuple[bool, str]: (是否允许执行, 错误信息)
        """
        # 如果不启用检查，直接允许
        if not self.enable_check:
            return True, ""

        # 检查 SQL 长度
        if len(sql_query) > self.max_sql_length:
            error_msg = f"SQL语句过长 ({len(sql_query)} > {self.max_sql_length})"
            logger.warning(f"查询被限制: {error_msg}")
            return False, error_msg

        # 解析 SQL 查询
        try:
            parsed_sql = self.sql_parser.parse_query(sql_query)
        except Exception as e:
            logger.error(f"SQL解析失败: {str(e)}")
            return False, "SQL解析失败，无法进行安全检查"

        # 分析安全风险
        security_analysis = self.sql_parser.analyze_security(parsed_sql)

        # 如果不允许执行，返回原因
        if not security_analysis['is_allowed']:
            error_msg = "; ".join(security_analysis['reasons'])
            logger.warning(f"查询被限制: {error_msg}")
            return False, error_msg

        # 特定操作检查
        operation_type = parsed_sql['operation_type']

        # 检查无 WHERE 子句的更新/删除操作
        if operation_type in {'UPDATE', 'DELETE'} and not parsed_sql['has_where']:
            error_msg = f"{operation_type}操作必须包含WHERE子句"
            logger.warning(f"查询被限制: {error_msg}")
            return False, error_msg

        # 检查无 LIMIT 子句的大规模查询
        if operation_type == 'SELECT' and not parsed_sql['has_limit']:
            # 检查是否有潜在的大规模查询风险
            if self._is_potential_large_query(parsed_sql):
                error_msg = "大规模SELECT查询必须包含LIMIT子句"
                logger.warning(f"查询被限制: {error_msg}")
                return False, error_msg

        return True, ""

    def _is_potential_large_query(self, parsed_sql: dict) -> bool:
        """
        检查是否是潜在的大规模查询

        基于表大小估计和查询复杂度判断
        """
        # 这里可以添加更复杂的逻辑，例如：
        # - 检查表的大小（如果有元数据）
        # - 检查是否涉及多个大表
        # - 检查是否有复杂的JOIN操作

        # 目前简单实现：如果涉及多个表或没有WHERE子句，则认为是潜在的大规模查询
        return len(parsed_sql['tables']) > 1 or not parsed_sql['has_where']


# 示例使用
if __name__ == "__main__":
    # 创建会话配置
    session_config = SessionConfigManager({
        "ENABLE_QUERY_CHECK": "true",
        "MAX_SQL_LENGTH": "5000"
    })

    # 创建查询限制器
    query_limiter = QueryLimiter(session_config)

    # 测试安全查询
    safe_query = "SELECT * FROM users WHERE age > 25"
    allowed, reason = query_limiter.check_query(safe_query)
    print(f"安全查询: 允许={allowed}, 原因={reason}")

    # 测试危险查询
    dangerous_query = "DROP TABLE users"
    allowed, reason = query_limiter.check_query(dangerous_query)
    print(f"危险查询: 允许={allowed}, 原因={reason}")

    # 测试无WHERE的更新
    update_query = "UPDATE users SET status = 'inactive'"
    allowed, reason = query_limiter.check_query(update_query)
    print(f"无WHERE更新: 允许={allowed}, 原因={reason}")

    # 测试大规模查询
    large_query = "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
    allowed, reason = query_limiter.check_query(large_query)
    print(f"大规模查询: 允许={allowed}, 原因={reason}")
