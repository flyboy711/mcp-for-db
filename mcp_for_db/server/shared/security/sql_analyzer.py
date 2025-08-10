import re
from typing import Dict, Any

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.server_mysql.config import SessionConfigManager
from mcp_for_db.server.core import SQLRiskLevel, EnvironmentType
from mcp_for_db.server.shared.security.sql_parser import SQLParser
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="mcp_sql_security.log")
logger.setLevel(LOG_LEVEL)


class SQLRiskAnalyzer:
    """SQL风险分析器，评估SQL操作的安全风险"""

    def __init__(self, session_config: SessionConfigManager):
        """
        初始化风险分析器

        Args:
            session_config: 会话配置管理器实例
        """
        self.session_config = session_config
        self.sql_parser = SQLParser(session_config)

        logger.info("SQL风险分析器初始化完成")

    def analyze_risk(self, sql_query: str) -> Dict[str, Any]:
        """
        分析SQL查询的风险

        Args:
            sql_query: SQL查询语句

        Returns:
            dict: 包含风险分析结果的字典
        """
        # 解析SQL
        parsed_result = self.sql_parser.parse_query(sql_query)

        # 确定风险等级
        risk_level = self._determine_risk_level(parsed_result)

        # 检查是否是危险操作
        is_dangerous = risk_level in {SQLRiskLevel.HIGH, SQLRiskLevel.CRITICAL}

        # 检查是否允许执行
        allowed_risk_levels = self.session_config.get('MYSQL_ALLOWED_RISK_LEVELS', set())

        # 确保类型一致性的检查
        is_allowed = False
        if allowed_risk_levels:
            if isinstance(next(iter(allowed_risk_levels)), str):
                # 如果配置中存储的是字符串，则比较名称
                is_allowed = risk_level.name in allowed_risk_levels
            else:
                # 如果配置中存储的是SQLRiskLevel对象，则直接比较
                is_allowed = risk_level in allowed_risk_levels

        return {
            'risk_level': risk_level,
            'is_dangerous': is_dangerous,
            'is_allowed': is_allowed,
            'operation': parsed_result['operation_type'],
            'category': parsed_result['category'],
            'tables': parsed_result['tables'],
            'has_where': parsed_result['has_where'],
            'has_limit': parsed_result['has_limit']
        }

    def _determine_risk_level(self, parsed_result: Dict[str, Any]) -> SQLRiskLevel:
        """根据解析结果确定风险等级"""
        op_type = parsed_result['operation_type'].upper()
        category = parsed_result['category'].upper()

        # DDL 操作
        if category == 'DDL':
            if op_type in {'DROP', 'TRUNCATE'}:
                return SQLRiskLevel.CRITICAL
            elif op_type in {'ALTER', 'RENAME'}:
                return SQLRiskLevel.HIGH
            else:  # CREATE
                return SQLRiskLevel.MEDIUM

        # DML 操作
        if op_type == 'DELETE':
            if not parsed_result['has_where']:
                return SQLRiskLevel.HIGH
            return SQLRiskLevel.MEDIUM
        elif op_type == 'UPDATE':
            if not parsed_result['has_where']:
                return SQLRiskLevel.HIGH
            return SQLRiskLevel.MEDIUM
        elif op_type == 'INSERT':
            return SQLRiskLevel.MEDIUM
        elif op_type == 'SELECT':
            return SQLRiskLevel.LOW

        # 元数据操作
        if op_type in {'SHOW', 'DESCRIBE', 'EXPLAIN'}:
            return SQLRiskLevel.LOW

        # 其他操作默认为中等风险
        return SQLRiskLevel.MEDIUM

    def _estimate_impact(self, parsed_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        估算查询影响范围

        Args:
            parsed_result: SQL 解析结果

        Returns:
            dict: 包含预估影响的字典
        """
        operation = parsed_result['operation_type']
        category = parsed_result['category']
        has_where = parsed_result['has_where']
        has_limit = parsed_result['has_limit']
        is_multi = parsed_result['multi_statement']

        impact = {
            'operation': operation,
            'needs_where': operation in {'UPDATE', 'DELETE'},
            'has_where': has_where,
            'needs_limit': operation == 'SELECT',
            'has_limit': has_limit,
            'is_multi_statement': is_multi,
            'estimated_rows': 0
        }

        # 根据环境类型调整估算
        if self.config.get("ENV_TYPE") == EnvironmentType.PRODUCTION:
            if category == 'DDL':
                impact['estimated_rows'] = int('inf')  # DDL 操作影响整个表
            elif operation in {'UPDATE', 'DELETE'}:
                impact['estimated_rows'] = float('inf') if not has_where else 1000
            elif operation == 'INSERT':
                impact['estimated_rows'] = 1  # 每次插入一行
            elif operation == 'SELECT':
                impact['estimated_rows'] = float('inf') if not has_limit else 100
        else:
            # 开发环境更宽松
            if category == 'DDL':
                impact['estimated_rows'] = 1000
            elif operation in {'UPDATE', 'DELETE'}:
                impact['estimated_rows'] = 10000 if not has_where else 100
            elif operation == 'INSERT':
                impact['estimated_rows'] = 1
            elif operation == 'SELECT':
                impact['estimated_rows'] = 1000 if not has_limit else 100

        # 多语句查询影响更大
        if is_multi:
            impact['estimated_rows'] *= parsed_result['statement_count']

        return impact

    def _empty_analysis_result(self) -> Dict[str, Any]:
        """返回空查询分析结果"""
        return {
            'operation': '',
            'operation_type': 'UNKNOWN',
            'is_dangerous': True,
            'affected_tables': [],
            'estimated_impact': {
                'operation': '',
                'needs_where': False,
                'has_where': False,
                'needs_limit': False,
                'has_limit': False,
                'is_multi_statement': False,
                'estimated_rows': 0
            },
            'risk_level': SQLRiskLevel.HIGH,
            'is_allowed': False,
            'reasons': ['空 SQL 查询'],
            'multi_statement': False,
            'statement_count': 0
        }

    def _fallback_analysis(self, sql_query: str) -> Dict[str, Any]:
        """当分析失败时，回退到基本分析"""
        try:
            # 尝试简单解析
            parsed_result = self.sql_parser._fallback_parse(sql_query)

            # 基本风险分析
            is_dangerous = self._check_dangerous_patterns(sql_query)

            # 简单影响评估
            impact = {
                'operation': parsed_result['operation_type'],
                'needs_where': parsed_result['operation_type'] in {'UPDATE', 'DELETE'},
                'has_where': parsed_result['has_where'],
                'needs_limit': parsed_result['operation_type'] == 'SELECT',
                'has_limit': parsed_result['has_limit'],
                'is_multi_statement': parsed_result['multi_statement'],
                'estimated_rows': 1000  # 保守估计
            }

            # 简单风险等级
            risk_level = SQLRiskLevel.MEDIUM
            if is_dangerous:
                risk_level = SQLRiskLevel.CRITICAL
            elif parsed_result['operation_type'] in {'DROP', 'TRUNCATE'}:
                risk_level = SQLRiskLevel.CRITICAL
            elif parsed_result['operation_type'] in {'DELETE', 'UPDATE'} and not parsed_result['has_where']:
                risk_level = SQLRiskLevel.HIGH

            return {
                'operation': parsed_result['operation_type'],
                'operation_type': parsed_result['category'],
                'is_dangerous': is_dangerous,
                'affected_tables': parsed_result['tables'],
                'estimated_impact': impact,
                'risk_level': risk_level,
                'is_allowed': not is_dangerous and risk_level in self.session_config.get("MYSQL_ALLOWED_RISK_LEVELS"),
                'reasons': ['回退分析模式'] if is_dangerous else [],
                'multi_statement': parsed_result['multi_statement'],
                'statement_count': parsed_result['statement_count']
            }
        except RuntimeError:
            # 完全失败时返回空结果
            return self._empty_analysis_result()

    def _check_dangerous_patterns(self, sql_query: str) -> bool:
        """检查是否匹配危险操作模式"""
        sql_upper = sql_query.upper()

        # 检查阻止的模式
        for pattern in self.session_config.get("MYSQL_BLOCKED_PATTERNS"):
            if re.search(pattern, sql_upper, re.IGNORECASE):
                return True

        # 检查高风险操作
        high_risk_ops = {'DROP', 'TRUNCATE', 'DELETE', 'UPDATE'}
        if any(op in sql_upper for op in high_risk_ops):
            # 检查是否有 WHERE 子句
            if 'DELETE' in sql_upper or 'UPDATE' in sql_upper:
                if 'WHERE' not in sql_upper:
                    return True

        return False


if __name__ == '__main__':
    # 初始化配置管理器
    session_config = SessionConfigManager({
        "MYSQL_ENV_TYPE": "production",
        "MYSQL_ALLOWED_RISK_LEVELS": "LOW,MEDIUM",
        "MYSQL_BLOCKED_PATTERNS": "DROP TABLE,TRUNCATE TABLE"
    })

    # 创建 SQL 风险分析器
    risk_analyzer = SQLRiskAnalyzer(session_config)

    # 分析 SQL 风险
    sql = "DELETE FROM users WHERE id = 1"
    analysis_result = risk_analyzer.analyze_risk(sql)

    print("风险分析结果:", analysis_result)
