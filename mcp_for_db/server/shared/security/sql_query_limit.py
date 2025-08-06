import logging
from typing import Tuple
from mcp_for_db.server.server_mysql.config import SessionConfigManager
from mcp_for_db.server.shared.security.sql_parser import SQLParser
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_security.log")
logger.setLevel(logging.INFO)


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
        self.enable_check = session_config.get('MYSQL_ENABLE_QUERY_CHECK', True)
        self.max_sql_length = session_config.get('MYSQL_MAX_SQL_LENGTH', 1000)

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

        # 分析安全风险 - 修改这个部分以避免类型错误
        try:
            security_analysis = self.sql_parser.analyze_security(parsed_sql)
        except Exception as e:
            # 如果安全分析失败，使用自定义的安全检查逻辑
            logger.warning(f"安全分析失败: {str(e)}, 使用备用检查逻辑")
            return self._fallback_security_check(parsed_sql)

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

    def _fallback_security_check(self, parsed_sql: dict) -> Tuple[bool, str]:
        """
        备用安全检查逻辑，当主要安全分析失败时使用

        Args:
            parsed_sql: 解析的SQL结果

        Returns:
            Tuple[bool, str]: (是否允许执行, 错误信息)
        """
        operation_type = parsed_sql['operation_type'].upper()

        # 检查高危操作
        high_risk_operations = {'DROP', 'TRUNCATE', 'ALTER', 'DELETE', 'UPDATE'}
        if operation_type in high_risk_operations:
            # 检查阻止模式
            blocked_patterns = self.session_config.get('MYSQL_BLOCKED_PATTERNS', [])
            if isinstance(blocked_patterns, str):
                blocked_patterns = [p.strip().upper() for p in blocked_patterns.split(',') if p.strip()]

            for pattern in blocked_patterns:
                if pattern in operation_type:
                    return False, f"操作 {operation_type} 被安全策略阻止"

            # 如果是删除或更新操作且没有WHERE子句，拒绝执行
            if operation_type in {'DELETE', 'UPDATE'} and not parsed_sql['has_where']:
                return False, f"{operation_type}操作没有WHERE子句，存在安全风险"

        # 检查是否访问敏感表
        sensitive_keywords = {'user', 'password', 'admin', 'config'}
        for table in parsed_sql.get('tables', []):
            table_lower = table.lower()
            if any(keyword in table_lower for keyword in sensitive_keywords):
                if operation_type in {'DROP', 'DELETE', 'UPDATE', 'ALTER'}:
                    return False, f"不允许对敏感表 {table} 执行 {operation_type} 操作"

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
    # 创建会话配置 - 添加更完整的配置
    session_config = SessionConfigManager({
        "MYSQL_ENABLE_QUERY_CHECK": "true",
        "MYSQL_MAX_SQL_LENGTH": "5000",
        "MYSQL_BLOCKED_PATTERNS": "DROP TABLE,TRUNCATE TABLE",
        "MYSQL_ALLOWED_RISK_LEVELS": "LOW,MEDIUM",
        "MYSQL_ALLOW_SENSITIVE_INFO": "false",
        "MYSQL_ENABLE_DATABASE_ISOLATION": "false"
    })

    # 创建查询限制器
    query_limiter = QueryLimiter(session_config)

    # 测试用例
    test_cases = [
        ("SELECT * FROM users WHERE age > 25", "安全查询"),
        ("DROP TABLE users", "危险查询"),
        ("UPDATE users SET status = 'inactive'", "无WHERE更新"),
        ("SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id", "大规模查询"),
        ("DELETE FROM logs WHERE created_at < '2023-01-01'", "带WHERE的删除"),
        ("INSERT INTO users (name, email) VALUES ('test', 'test@example.com')", "插入操作"),
    ]

    print("=== SQL查询安全检查测试 ===\n")

    for sql_query, description in test_cases:
        print(f"测试: {description}")
        print(f"SQL: {sql_query}")

        try:
            allowed, reason = query_limiter.check_query(sql_query)
            if allowed:
                print("✅ 允许执行")
            else:
                print(f"🚫 拒绝执行: {reason}")
        except Exception as e:
            print(f"❌ 检查失败: {str(e)}")

        print("-" * 60)

    print("=== 测试完成 ===")
