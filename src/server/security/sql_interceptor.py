import logging
from typing import Dict, Any, Optional
import asyncio

from server.config import AppConfigManager, SQLRiskLevel
from server.security.sql_parser import SQLParser
from server.security.db_scope_check import DatabaseScopeChecker, DatabaseScopeViolation
from server.security.sql_analyzer import SQLRiskAnalyzer

logger = logging.getLogger(__name__)


class SecurityException(Exception):
    """安全相关异常基类"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SQLOperationException(SecurityException):
    """SQL操作异常"""
    pass


class SQLInterceptor:
    """增强的SQL操作拦截器，提供全面的SQL安全检查和拦截功能"""

    def __init__(self, config_manager: AppConfigManager):
        """
        初始化SQL拦截器

        Args:
            config_manager: 配置管理器实例
        """
        self.config = config_manager
        self.sql_parser = SQLParser(config_manager)
        self.risk_analyzer = SQLRiskAnalyzer(config_manager)

        # 初始化数据库范围检查器
        self.database_checker = None
        if config_manager.ENABLE_DATABASE_ISOLATION and config_manager.MYSQL_DATABASE:
            self.database_checker = DatabaseScopeChecker(config_manager)
            logger.info(f"数据库隔离已启用: 允许数据库={config_manager.MYSQL_DATABASE}, "
                        f"访问级别={config_manager.DATABASE_ACCESS_LEVEL.value}")

        logger.info("SQL拦截器初始化完成")

    async def check_operation(self, sql_query: str) -> Dict[str, Any]:
        """
        全面检查SQL操作是否允许执行，返回详细检查结果

        Args:
            sql_query: SQL查询语句

        Returns:
            dict: 包含详细检查结果的字典

        Raises:
            SQLOperationException: 当操作被拒绝时抛出
        """
        # 创建结果字典
        result = {
            'is_allowed': False,
            'sql': sql_query,
            'violations': [],
            'risk_level': SQLRiskLevel.LOW,
            'operation_type': 'UNKNOWN',
            'affected_tables': [],
            'database_violations': [],
            'security_analysis': {}
        }

        try:
            # 步骤1: 基本SQL检查
            self._check_basic_sql(sql_query, result)

            # 步骤2: 解析SQL
            parsed_result = self._parse_sql(sql_query, result)

            # 步骤3: 数据库范围检查
            self._check_database_scope(sql_query, result)

            # 步骤4: 风险分析
            risk_analysis = self._analyze_risk(sql_query, parsed_result, result)

            # 步骤5: 最终决策
            self._make_final_decision(result, risk_analysis)

            # 记录成功日志
            if result['is_allowed']:
                logger.info(
                    f"SQL操作检查通过 - 操作: {result['operation_type']}, "
                    f"风险等级: {result['risk_level'].name}, "
                    f"影响表: {', '.join(result['affected_tables'])}"
                )

            return result

        except SQLOperationException as e:
            # 记录异常并返回结果
            logger.error(f"SQL操作被拒绝: {e.message}")
            result['violations'].append(e.message)
            if e.details:
                result.update(e.details)
            return result
        except Exception as e:
            # 处理意外错误
            error_msg = f"安全检查失败: {str(e)}"
            logger.exception(error_msg)
            result['violations'].append(error_msg)
            return result

    def _check_basic_sql(self, sql_query: str, result: Dict[str, Any]) -> None:
        """执行基本的SQL检查"""
        # 检查SQL是否为空
        if not sql_query or not sql_query.strip():
            raise SQLOperationException("SQL语句不能为空")

        # 检查SQL长度
        max_length = self.config.MAX_SQL_LENGTH
        if len(sql_query) > max_length:
            raise SQLOperationException(
                f"SQL语句长度({len(sql_query)})超出限制({max_length})",
                {'max_sql_length': max_length}
            )

        # 检查是否包含阻止的模式
        if self.config.should_block_sql(sql_query):
            raise SQLOperationException("SQL包含被阻止的模式")

    def _parse_sql(self, sql_query: str, result: Dict[str, Any]) -> Dict[str, Any]:
        """解析SQL并更新结果"""
        try:
            parsed_result = self.sql_parser.parse_query(sql_query)
            result.update({
                'operation_type': parsed_result['operation_type'],
                'category': parsed_result['category'],
                'affected_tables': parsed_result['tables'],
                'has_where': parsed_result['has_where'],
                'has_limit': parsed_result['has_limit'],
                'multi_statement': parsed_result['multi_statement'],
                'statement_count': parsed_result['statement_count'],
                'parsed_result': parsed_result
            })

            # 检查SQL是否有效
            if not parsed_result['is_valid']:
                raise SQLOperationException("SQL语句格式无效")

            # 检查操作类型是否支持
            supported_operations = (
                    self.config.DDL_OPERATIONS |
                    self.config.DML_OPERATIONS |
                    self.config.METADATA_OPERATIONS
            )

            if parsed_result['operation_type'] not in supported_operations:
                raise SQLOperationException(
                    f"不支持的SQL操作: {parsed_result['operation_type']}",
                    {'supported_operations': list(supported_operations)}
                )

            return parsed_result
        except Exception as e:
            raise SQLOperationException(f"SQL解析失败: {str(e)}")

    def _check_database_scope(self, sql_query: str, result: Dict[str, Any]) -> None:
        """执行数据库范围检查"""
        if not self.database_checker:
            return

        try:
            # 检查数据库范围
            is_allowed, violations = self.database_checker.check_query(sql_query)
            result['database_violations'] = violations

            if not is_allowed:
                violation_details = "; ".join(violations)
                raise SQLOperationException(
                    f"数据库访问违规: {violation_details}",
                    {'database_report': self.database_checker.get_database_access_report(sql_query)}
                )
        except DatabaseScopeViolation as e:
            # 处理数据库范围违规
            result['database_violations'] = e.violations
            raise SQLOperationException(
                f"数据库范围违规: {e.message}",
                {'violations': e.violations}
            )
        except Exception as e:
            raise SQLOperationException(f"数据库范围检查失败: {str(e)}")

    def _analyze_risk(self, sql_query: str, parsed_result: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """执行风险分析"""
        try:
            risk_analysis = self.risk_analyzer.analyze_risk(sql_query)
            result.update({
                'risk_level': risk_analysis['risk_level'],
                'is_dangerous': risk_analysis['is_dangerous'],
                'estimated_impact': risk_analysis.get('estimated_impact', {}),
                'security_analysis': risk_analysis
            })

            # 检查是否是危险操作
            if risk_analysis['is_dangerous']:
                raise SQLOperationException(
                    f"检测到危险操作: {risk_analysis['operation']}",
                    {'risk_details': risk_analysis}
                )

            return risk_analysis
        except Exception as e:
            raise SQLOperationException(f"风险分析失败: {str(e)}")

    def _make_final_decision(self, result: Dict[str, Any], risk_analysis: Dict[str, Any]) -> None:
        """根据风险分析做出最终决策"""
        # 检查操作是否被允许
        if not risk_analysis['is_allowed']:
            allowed_levels = [level.name for level in self.config.ALLOWED_RISK_LEVELS]
            raise SQLOperationException(
                f"当前操作风险等级({risk_analysis['risk_level'].name})不被允许执行，"
                f"允许的风险等级: {allowed_levels}",
                {
                    'risk_level': risk_analysis['risk_level'].name,
                    'allowed_risk_levels': allowed_levels
                }
            )

        # 所有检查通过
        result['is_allowed'] = True

    async def enforce_operation(self, sql_query: str) -> Dict[str, Any]:
        """
        强制执行SQL操作检查，如果被拒绝则抛出异常

        Args:
            sql_query: SQL查询语句

        Returns:
            dict: 包含详细检查结果的字典（仅当允许时）

        Raises:
            SQLOperationException: 当操作被拒绝时抛出
        """
        result = await self.check_operation(sql_query)
        if not result['is_allowed']:
            violations = "\n".join(result['violations'])
            raise SQLOperationException(
                f"SQL操作被拒绝: {violations}",
                {'check_result': result}
            )
        return result

    def get_security_report(self, sql_query: str) -> Dict[str, Any]:
        """
        获取SQL操作的完整安全报告

        Args:
            sql_query: SQL查询语句

        Returns:
            dict: 包含完整安全报告的字典
        """
        report = {
            'sql': sql_query,
            'basic_check': {},
            'parsing_result': {},
            'database_check': {},
            'risk_analysis': {},
            'decision': 'PENDING'
        }

        try:
            # 基本检查
            report['basic_check'] = self._get_basic_check_report(sql_query)

            # SQL解析
            report['parsing_result'] = self.sql_parser.parse_query(sql_query)

            # 数据库检查
            if self.database_checker:
                report['database_check'] = self.database_checker.get_database_access_report(sql_query)

            # 风险分析
            report['risk_analysis'] = self.risk_analyzer.analyze_risk(sql_query)

            # 最终决策
            report['decision'] = 'ALLOWED' if self._is_operation_allowed(report) else 'DENIED'

        except Exception as e:
            report['error'] = str(e)
            report['decision'] = 'ERROR'

        return report

    def _get_basic_check_report(self, sql_query: str) -> Dict[str, Any]:
        """获取基本检查报告"""
        return {
            'is_empty': not bool(sql_query.strip()),
            'length': len(sql_query),
            'max_length': self.config.MAX_SQL_LENGTH,
            'is_over_length': len(sql_query) > self.config.MAX_SQL_LENGTH,
            'contains_blocked_patterns': self.config.should_block_sql(sql_query)
        }

    def _is_operation_allowed(self, report: Dict[str, Any]) -> bool:
        """根据报告判断操作是否允许"""
        # 基本检查失败
        if report['basic_check']['is_empty']:
            return False
        if report['basic_check']['is_over_length']:
            return False
        if report['basic_check']['contains_blocked_patterns']:
            return False

        # SQL解析失败
        if not report['parsing_result'].get('is_valid', False):
            return False

        # 数据库检查失败
        if report['database_check'].get('violations', []):
            return False

        # 风险分析不允许
        if not report['risk_analysis'].get('is_allowed', False):
            return False

        return True


async def test_sql_interceptor():
    """测试SQL拦截器功能"""
    logger.info("=== 开始SQL拦截器测试 ===")

    # 初始化配置管理器
    config_manager = AppConfigManager()

    # 创建SQL拦截器
    interceptor = SQLInterceptor(config_manager)

    # 测试用例
    test_cases = [
        ("SELECT * FROM t_users", "简单SELECT查询"),
        ("DROP TABLE _users", "危险DROP操作"),
        ("UPDATE t_users SET age = age * 1.1", "无WHERE条件的UPDATE"),
        ("SELECT * FROM tpch_tiny.orders", "跨数据库查询"),
        ("SHOW DATABASES", "元数据查询"),
        ("", "空查询"),
        ("A" * (config_manager.MAX_SQL_LENGTH + 100), "超长SQL查询")
    ]

    for sql, description in test_cases:
        logger.info(f"\n测试用例: {description}")
        logger.info(f"SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")

        try:
            result = await interceptor.check_operation(sql)
            if result['is_allowed']:
                logger.info("SQL操作允许执行")
            else:
                logger.warning(f"SQL操作被拒绝: {result['violations']}")
        except Exception as e:
            logger.error(f"测试失败: {str(e)}")

        logger.info("-" * 50)

    logger.info("=== SQL拦截器测试完成 ===")


if __name__ == "__main__":
    asyncio.run(test_sql_interceptor())
