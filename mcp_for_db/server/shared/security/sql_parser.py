import sqlparse
import re
from typing import List, Dict, Any

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.server_mysql.config import SessionConfigManager
from mcp_for_db.server.core import SQLRiskLevel, DatabaseAccessLevel
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="sql_security.log")
logger.setLevel(LOG_LEVEL)


class SQLParser:
    """
    SQL 解析器，提供较为健壮的 SQL 解析和安全分析功能
    """

    def __init__(self, session_config: SessionConfigManager):
        """
        初始化 SQL 解析器
        :param session_config: 会话配置管理器实例
        """
        self.session_config = session_config

        # 定义操作类型集合
        self.ddl_operations = {'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME'}
        self.dml_operations = {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE'}
        self.metadata_operations = {'SHOW', 'DESC', 'DESCRIBE', 'EXPLAIN', 'HELP', 'ANALYZE', 'CHECK', 'CHECKSUM',
                                    'OPTIMIZE', 'SET', 'USE', 'BEGIN', 'COMMIT', 'ROLLBACK', 'START', 'KILL'}
        self.procedure_operations = {'CALL', 'EXECUTE', 'EXEC'}

    def parse_query(self, sql_query: str) -> Dict[str, Any]:
        """
        解析 SQL 查询，返回详细的解析结果

        Args:
            sql_query: SQL 查询语句

        Returns:
            Dict: 包含解析结果的字典
        """
        if not sql_query or not sql_query.strip():
            return self._empty_result()

        try:
            # 标准化和格式化 SQL
            formatted_sql = self._format_sql(sql_query)

            # 解析 SQL 语句
            parsed = sqlparse.parse(formatted_sql)

            # 处理多语句 SQL
            if len(parsed) > 1:
                return self._process_multi_statement(parsed)

            # 单语句处理
            stmt = parsed[0]
            return self._process_single_statement(stmt, formatted_sql)

        except Exception as e:
            logger.warning(f"SQL解析错误: {str(e)}")
            return self._fallback_parse(sql_query)

    def analyze_security(self, parsed_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析 SQL 的安全风险，基于会话配置

        Args:
            parsed_result: parse_query 返回的结果

        Returns:
            Dict: 包含安全分析结果的字典
        """
        analysis = {
            'risk_level': self._determine_risk_level(parsed_result),
            'is_allowed': True,
            'reasons': []
        }

        # 检查风险等级是否允许
        allowed_risk_levels = self.session_config.get('MYSQL_ALLOWED_RISK_LEVELS', set())
        if analysis['risk_level'] not in allowed_risk_levels:
            analysis['is_allowed'] = False
            analysis['reasons'].append(
                f"风险等级 {analysis['risk_level'].name} 在当前会话中被禁止"
            )

        # 检查是否包含阻止的模式
        blocked_patterns = self.session_config.get('MYSQL_BLOCKED_PATTERNS', [])
        if self._contains_blocked_pattern(parsed_result['original_query'], blocked_patterns):
            analysis['is_allowed'] = False
            analysis['reasons'].append(
                "SQL 包含被阻止的模式"
            )

        # 检查敏感信息访问
        allow_sensitive_info = self.session_config.get('MYSQL_ALLOW_SENSITIVE_INFO', False)
        if not allow_sensitive_info and self._contains_sensitive_info(parsed_result):
            analysis['is_allowed'] = False
            analysis['reasons'].append(
                "SQL 可能访问敏感信息"
            )

        # 检查数据库隔离
        enable_database_isolation = self.session_config.get('MYSQL_ENABLE_DATABASE_ISOLATION', False)
        if enable_database_isolation:
            if not self._is_database_access_allowed(parsed_result):
                analysis['is_allowed'] = False
                analysis['reasons'].append(
                    "数据库隔离策略禁止此操作"
                )

        return analysis

    def _format_sql(self, sql_query: str) -> str:
        """标准化 SQL 查询格式"""
        # 去除多余空白和注释
        return sqlparse.format(
            sql_query,
            strip_comments=True,
            reindent=True,
            keyword_case='upper'
        )

    def _process_single_statement(self, stmt: sqlparse.sql.Statement, formatted_sql: str) -> Dict[str, Any]:
        """处理单个 SQL 语句（增强版）"""
        # 获取操作类型
        operation_type = self._get_operation_type(stmt)

        # 确定操作类别
        category = self._get_operation_category(operation_type)

        # 提取表名
        tables = self._extract_tables(stmt)

        # 检查 WHERE 子句
        has_where = self._has_where_clause(stmt)

        # 检查 LIMIT 子句
        has_limit = self._has_limit_clause(stmt)

        # 检查子查询
        has_subquery = self._has_subquery(stmt)

        return {
            'operation_type': operation_type,
            'tables': tables,
            'has_where': has_where,
            'has_limit': has_limit,
            'is_valid': bool(operation_type),
            'normalized_query': formatted_sql,
            'original_query': stmt.value,
            'category': category,
            'multi_statement': False,
            'statement_count': 1,
            'has_subquery': has_subquery
        }

    def _process_multi_statement(self, statements: List[sqlparse.sql.Statement]) -> Dict[str, Any]:
        """处理多语句 SQL"""
        # 收集所有语句的信息
        results = []
        for stmt in statements:
            formatted_sql = self._format_sql(stmt.value)
            results.append(self._process_single_statement(stmt, formatted_sql))

        # 确定整体风险最高的操作类型和类别
        highest_risk_op = ''
        highest_risk_category = ''
        highest_risk_level = SQLRiskLevel.LOW

        for result in results:
            risk_level = self._determine_risk_level(result)
            if risk_level.value > highest_risk_level.value:
                highest_risk_level = risk_level
                highest_risk_op = result['operation_type']
                highest_risk_category = result['category']

        # 合并所有表名
        all_tables = set()
        for result in results:
            all_tables.update(result['tables'])

        # 检查是否有 WHERE 或 LIMIT 子句
        has_where = any(result['has_where'] for result in results)
        has_limit = any(result['has_limit'] for result in results)

        return {
            'operation_type': highest_risk_op,
            'tables': list(all_tables),
            'has_where': has_where,
            'has_limit': has_limit,
            'is_valid': True,
            'normalized_query': "\n".join(result['normalized_query'] for result in results),
            'original_query': "\n".join(result['original_query'] for result in results),
            'category': highest_risk_category,
            'multi_statement': True,
            'statement_count': len(statements),
            'sub_statements': results
        }

    def _get_operation_type(self, stmt: sqlparse.sql.Statement) -> str:
        """获取 SQL 操作类型"""
        # 获取语句类型
        stmt_type = stmt.get_type()

        if stmt_type:
            return stmt_type.upper()

        # 如果无法确定类型，检查第一个关键字
        first_token = stmt.token_first(skip_ws=True, skip_cm=True)
        if first_token:
            token_value = first_token.value.upper()

            # 处理 SHOW 语句
            if token_value == 'SHOW':
                # 检查 SHOW 的具体类型
                next_token = stmt.token_next(first_token, skip_ws=True, skip_cm=True)
                if next_token:
                    next_value = next_token.value.upper()

                    # 处理 SHOW TABLES - 新增这部分
                    if next_value == 'TABLES':
                        return 'SHOW TABLES'

                    # 处理 SHOW FULL PROCESSLIST
                    elif next_value == 'FULL':
                        next_next = stmt.token_next(next_token, skip_ws=True, skip_cm=True)
                        if next_next and next_next.value.upper() == 'PROCESSLIST':
                            return 'SHOW PROCESSLIST'

                    # 处理 SHOW VARIABLES
                    elif next_value == 'VARIABLES':
                        return 'SHOW VARIABLES'

                    # 处理 SHOW ENGINE
                    elif next_value == 'ENGINE':
                        next_next = stmt.token_next(next_token, skip_ws=True, skip_cm=True)
                        if next_next and next_next.value.upper() == 'INNODB':
                            next_next_next = stmt.token_next(next_next, skip_ws=True, skip_cm=True)
                            if next_next_next and next_next_next.value.upper() == 'STATUS':
                                return 'SHOW ENGINE INNODB STATUS'

                    # 处理其他 SHOW 命令
                    else:
                        return f'SHOW {next_value}'

                # 默认返回 SHOW
                return 'SHOW'

            # 返回第一个关键字
            return token_value

        return "UNKNOWN"

    def _get_operation_category(self, operation_type: str) -> str:
        """确定操作类别（DDL、DML 或元数据）"""
        if operation_type in self.ddl_operations:
            return 'DDL'
        elif operation_type in self.dml_operations:
            return 'DML'
        elif operation_type in self.metadata_operations or operation_type.startswith('SHOW'):
            return 'METADATA'
        elif operation_type in self.procedure_operations:
            return 'PROCEDURE'
        else:
            return 'UNKNOWN'

    def _extract_tables(self, stmt: sqlparse.sql.Statement) -> List[str]:
        """从 SQL 语句中提取所有表名（增强版）"""
        tables = set()
        sql_str = str(stmt).upper()

        # 处理 SHOW 语句
        if sql_str.startswith('SHOW '):
            # SHOW FULL PROCESSLIST - 没有特定表
            if 'PROCESSLIST' in sql_str:
                return []

            # SHOW VARIABLES - 没有特定表
            if 'VARIABLES' in sql_str:
                return []

            # SHOW ENGINE INNODB STATUS - 没有特定表
            if 'ENGINE INNODB STATUS' in sql_str:
                return []

            # 其他 SHOW 语句尝试提取表名
            match = re.search(r'\bFROM\s+([\w\.]+)', sql_str)
            if match:
                tables.add(match.group(1))
            return list(tables)

        # 处理 SELECT 语句
        if sql_str.startswith('SELECT'):
            # 提取 FROM 子句中的表
            from_matches = re.finditer(r'\bFROM\s+([\w\.]+)', sql_str)
            for match in from_matches:
                table_name = match.group(1).strip()
                if '.' in table_name:
                    tables.add(table_name)
                else:
                    tables.add(table_name)

            # 提取 JOIN 子句中的表
            join_matches = re.finditer(r'\bJOIN\s+([\w\.]+)', sql_str)
            for match in join_matches:
                table_name = match.group(1).strip()
                if '.' in table_name:
                    tables.add(table_name)
                else:
                    tables.add(table_name)

        # 处理 UPDATE 语句
        if sql_str.startswith('UPDATE'):
            update_matches = re.search(r'\bUPDATE\s+([\w\.]+)', sql_str)
            if update_matches:
                table_name = update_matches.group(1).strip()
                if '.' in table_name:
                    tables.add(table_name)
                else:
                    tables.add(table_name)

        # 处理 DELETE 语句
        if sql_str.startswith('DELETE'):
            delete_matches = re.search(r'\bDELETE\s+FROM\s+([\w\.]+)', sql_str)
            if delete_matches:
                table_name = delete_matches.group(1).strip()
                if '.' in table_name:
                    tables.add(table_name)
                else:
                    tables.add(table_name)

        # 处理 INSERT 语句
        if sql_str.startswith('INSERT'):
            insert_matches = re.search(r'\bINSERT\s+INTO\s+([\w\.]+)', sql_str)
            if insert_matches:
                table_name = insert_matches.group(1).strip()
                if '.' in table_name:
                    tables.add(table_name)
                else:
                    tables.add(table_name)

        # 处理其他语句中的表名
        table_matches = re.finditer(r'\b(?:FROM|JOIN|UPDATE|INTO|TABLE)\s+([\w\.]+)', sql_str)
        for match in table_matches:
            table_name = match.group(1).strip()
            if '.' in table_name:
                tables.add(table_name)
            else:
                tables.add(table_name)

        return list(tables)

    def _has_where_clause(self, stmt: sqlparse.sql.Statement) -> bool:
        """检查 SQL 语句是否包含 WHERE 子句（增强版）"""
        # SHOW 语句通常没有 WHERE 子句
        sql_str = str(stmt).upper()
        if sql_str.startswith('SHOW '):
            return False

        # 使用正则表达式检查 WHERE 关键字
        return 'WHERE' in sql_str

    def _has_limit_clause(self, stmt: sqlparse.sql.Statement) -> bool:
        """检查 SQL 语句是否包含 LIMIT 子句（增强版）"""
        # SHOW 语句通常没有 LIMIT 子句
        sql_str = str(stmt).upper()
        if sql_str.startswith('SHOW '):
            return False

        # 使用正则表达式检查 LIMIT 关键字
        return 'LIMIT' in sql_str

    def _has_subquery(self, stmt: sqlparse.sql.Statement) -> bool:
        """检查 SQL 语句是否包含子查询"""
        # 使用正则表达式检查子查询模式
        sql_str = str(stmt).upper()
        return re.search(r'\bSELECT\s+.*?\bFROM\s+\(', sql_str) is not None

    def _determine_risk_level(self, parsed_result: Dict[str, Any]) -> SQLRiskLevel:
        """根据解析结果确定风险等级（增强版）"""
        op_type = parsed_result['operation_type']
        category = parsed_result['category']

        # 元数据操作通常是低风险
        if category == 'METADATA':
            return SQLRiskLevel.LOW

        # DDL 操作通常有高风险
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

        # 其他操作默认为中等风险
        return SQLRiskLevel.MEDIUM

    def _contains_blocked_pattern(self, sql_query: str, blocked_patterns: List[str]) -> bool:
        """检查 SQL 是否包含被阻止的模式"""
        if not blocked_patterns:
            return False

        sql_upper = sql_query.upper()
        return any(pattern in sql_upper for pattern in blocked_patterns)

    def _contains_sensitive_info(self, parsed_result: Dict[str, Any]) -> bool:
        """检查 SQL 是否可能访问敏感信息"""
        # 简单的关键字检测
        sensitive_keywords = {'password', 'passwd', 'secret', 'token', 'credit', 'card', 'ssn'}

        # 检查表名
        for table in parsed_result['tables']:
            if any(kw in table.lower() for kw in sensitive_keywords):
                return True

        # 检查 SQL 语句
        sql_lower = parsed_result['original_query'].lower()
        if any(kw in sql_lower for kw in sensitive_keywords):
            return True

        return False

    def _is_database_access_allowed(self, parsed_result: Dict[str, Any]) -> bool:
        """检查数据库访问是否符合隔离策略"""
        # 获取数据库访问级别
        access_level_str = self.session_config.get('MYSQL_DATABASE_ACCESS_LEVEL', 'permissive')
        try:
            access_level = DatabaseAccessLevel(access_level_str.lower())
        except ValueError:
            access_level = DatabaseAccessLevel.PERMISSIVE

        # 宽松模式允许所有访问
        if access_level == DatabaseAccessLevel.PERMISSIVE:
            return True

        # 获取配置的数据库名称
        configured_db = self.session_config.get('MYSQL_DATABASE', '')

        # 检查每个表是否在允许的数据库中
        for table in parsed_result['tables']:
            # 如果表名包含数据库名，检查是否匹配
            if '.' in table:
                db_name, _ = table.split('.', 1)
                if db_name != configured_db:
                    return False
            # 严格模式不允许访问其他数据库
            elif access_level == DatabaseAccessLevel.STRICT:
                return False

        return True

    def _fallback_parse(self, sql_query: str) -> Dict[str, Any]:
        """当高级解析失败时，回退到基本字符串解析"""
        sql_upper = sql_query.strip().upper()
        parts = sql_upper.split()

        operation_type = parts[0] if parts else "UNKNOWN"

        # 确定操作类别
        category = 'UNKNOWN'
        if operation_type in self.ddl_operations:
            category = 'DDL'
        elif operation_type in self.dml_operations:
            category = 'DML'
        elif operation_type in self.metadata_operations or operation_type.startswith('SHOW'):
            category = 'METADATA'
        elif operation_type in self.procedure_operations:
            category = 'PROCEDURE'

        # 基本的表名提取
        tables = []
        for i, word in enumerate(parts):
            if word in {'FROM', 'JOIN', 'UPDATE', 'INTO', 'TABLE'}:
                if i + 1 < len(parts):
                    table = parts[i + 1].strip('`;')
                    if table not in {'SELECT', 'WHERE', 'SET'}:
                        tables.append(table)

        # 简单检查 WHERE 子句
        has_where = 'WHERE' in sql_upper

        # 简单检查 LIMIT 子句
        has_limit = 'LIMIT' in sql_upper

        return {
            'operation_type': operation_type,
            'tables': list(set(tables)),
            'has_where': has_where,
            'has_limit': has_limit,
            'is_valid': bool(operation_type),
            'normalized_query': sql_query,
            'original_query': sql_query,
            'category': category,
            'multi_statement': ';' in sql_query.strip(),
            'statement_count': sql_query.count(';') + 1 if sql_query.strip() else 0
        }

    def _empty_result(self) -> Dict[str, Any]:
        """返回空查询结果"""
        return {
            'operation_type': 'UNKNOWN',
            'tables': [],
            'has_where': False,
            'has_limit': False,
            'is_valid': False,
            'normalized_query': '',
            'original_query': '',
            'category': 'UNKNOWN',
            'multi_statement': False,
            'statement_count': 0
        }


if __name__ == '__main__':
    # 创建会话配置管理器
    session_config = SessionConfigManager({
        "MYSQL_ALLOWED_RISK_LEVELS": "LOW,MEDIUM",
        "MYSQL_BLOCKED_PATTERNS": "DROP TABLE,DELETE FROM",
        "MYSQL_ALLOW_SENSITIVE_INFO": "false",
        "MYSQL_ENABLE_DATABASE_ISOLATION": "true",
        "MYSQL_DATABASE_ACCESS_LEVEL": "restricted",
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    })

    # 创建 SQL 解析器
    sql_parser = SQLParser(session_config)

    # 测试 SHOW 语句
    test_cases = [
        "SHOW FULL PROCESSLIST",
        "SHOW VARIABLES LIKE 'max_connections'",
        "SHOW ENGINE INNODB STATUS",
        "SELECT * FROM INFORMATION_SCHEMA.INNODB_TRX",
        "SHOW OPEN TABLES WHERE In_use > 0"
    ]

    for sql in test_cases:
        print(f"\n测试 SQL: {sql}")
        parsed_result = sql_parser.parse_query(sql)
        print("解析结果:")
        print(f"  操作类型: {parsed_result['operation_type']}")
        print(f"  类别: {parsed_result['category']}")
        print(f"  表名: {parsed_result['tables']}")
        print(f"  有 WHERE: {parsed_result['has_where']}")
        print(f"  有 LIMIT: {parsed_result['has_limit']}")

        security_analysis = sql_parser.analyze_security(parsed_result)
        print("安全分析:")
        print(f"  风险等级: {security_analysis['risk_level'].name}")
        print(f"  是否允许: {security_analysis['is_allowed']}")
        if not security_analysis['is_allowed']:
            print(f"  原因: {', '.join(security_analysis['reasons'])}")
