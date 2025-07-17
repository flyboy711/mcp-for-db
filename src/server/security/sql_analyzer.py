import re
import logging
from typing import Dict, Any

from server.config import SessionConfigManager, SQLRiskLevel, EnvironmentType
from server.security.sql_parser import SQLParser

logger = logging.getLogger(__name__)


class SQLRiskAnalyzer:
    """SQL 风险分析器，提供全面的 SQL 风险评估和安全检查"""

    def __init__(self, config_manager: SessionConfigManager):
        """
        初始化 SQL 风险分析器
        :param config_manager: 配置管理器实例
        """
        self.config = config_manager
        self.sql_parser = SQLParser(config_manager)

        logger.info(f"SQL风险分析器初始化 - 环境: {self.config.get("ENV_TYPE")}")
        logger.info(f"允许的风险等级: {[level for level in self.config.get("ALLOWED_RISK_LEVELS")]}")
        logger.info(f"阻止的模式: {self.config.get("BLOCKED_PATTERNS")}")

    def analyze_risk(self, sql_query: str) -> Dict[str, Any]:
        """
        全面分析 SQL 查询的风险级别和安全影响

        Args:
            sql_query: SQL 查询语句

        Returns:
            dict: 包含风险分析结果的字典
        """
        # 处理空 SQL
        if not sql_query or not sql_query.strip():
            return self._empty_analysis_result()

        try:
            # 解析 SQL
            parsed_result = self.sql_parser.parse_query(sql_query)

            # 安全分析
            security_analysis = self.sql_parser.analyze_security(parsed_result)

            # 风险分析
            risk_level = self._calculate_risk_level(parsed_result, security_analysis)

            # 影响评估
            impact_analysis = self._estimate_impact(parsed_result)

            # 构建完整结果
            return {
                'operation': parsed_result['operation_type'],
                'operation_type': parsed_result['category'],
                'is_dangerous': security_analysis['is_allowed'] is False,
                'affected_tables': parsed_result['tables'],
                'estimated_impact': impact_analysis,
                'risk_level': risk_level,
                'is_allowed': security_analysis['is_allowed'],
                'reasons': security_analysis['reasons'],
                'multi_statement': parsed_result['multi_statement'],
                'statement_count': parsed_result['statement_count'],
                'security_analysis': security_analysis
            }
        except Exception as e:
            logger.error(f"SQL风险分析失败: {str(e)}")
            return self._fallback_analysis(sql_query)

    def _calculate_risk_level(self, parsed_result: Dict[str, Any], security_analysis: Dict[str, Any]) -> SQLRiskLevel:
        """
        计算操作风险等级

        规则：
        1. 如果被安全分析标记为不允许，则使用最高风险等级
        2. 根据操作类型和上下文确定风险等级
        """
        # 如果被安全分析标记为不允许，使用最高风险等级
        if not security_analysis['is_allowed']:
            return SQLRiskLevel.CRITICAL

        operation = parsed_result['operation_type']
        category = parsed_result['category']
        has_where = parsed_result['has_where']
        has_limit = parsed_result['has_limit']
        is_multi = parsed_result['multi_statement']

        # DDL 操作
        if category == 'DDL':
            if operation in {'DROP', 'TRUNCATE'}:
                return SQLRiskLevel.CRITICAL
            elif operation in {'ALTER', 'RENAME'}:
                return SQLRiskLevel.HIGH
            else:  # CREATE
                return SQLRiskLevel.MEDIUM

        # DML 操作
        if operation == 'DELETE':
            return SQLRiskLevel.CRITICAL if not has_where else SQLRiskLevel.MEDIUM
        elif operation == 'UPDATE':
            return SQLRiskLevel.HIGH if not has_where else SQLRiskLevel.MEDIUM
        elif operation == 'INSERT':
            return SQLRiskLevel.MEDIUM
        elif operation == 'SELECT':
            # 没有 LIMIT 的大查询可能风险更高
            return SQLRiskLevel.MEDIUM if not has_limit else SQLRiskLevel.LOW

        # 元数据操作
        if category == 'METADATA':
            return SQLRiskLevel.LOW

        # 多语句查询风险更高
        if is_multi:
            return SQLRiskLevel.HIGH

        # 默认情况
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
                'is_allowed': not is_dangerous and risk_level in self.config.get("ALLOWED_RISK_LEVELS"),
                'reasons': ['回退分析模式'] if is_dangerous else [],
                'multi_statement': parsed_result['multi_statement'],
                'statement_count': parsed_result['statement_count']
            }
        except Exception:
            # 完全失败时返回空结果
            return self._empty_analysis_result()

    def _check_dangerous_patterns(self, sql_query: str) -> bool:
        """检查是否匹配危险操作模式"""
        sql_upper = sql_query.upper()

        # 检查阻止的模式
        for pattern in self.config.get("BLOCKED_PATTERNS"):
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
        "ENV_TYPE": "production",
        "ALLOWED_RISK_LEVELS": "LOW,MEDIUM",
        "BLOCKED_PATTERNS": "DROP TABLE,TRUNCATE TABLE"
    })

    # 创建 SQL 风险分析器
    risk_analyzer = SQLRiskAnalyzer(session_config)

    # 分析 SQL 风险
    sql = "DELETE FROM users WHERE id = 1"
    analysis_result = risk_analyzer.analyze_risk(sql)

    print("风险分析结果:", analysis_result)
