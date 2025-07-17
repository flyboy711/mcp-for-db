import re
import logging
from typing import Set, List, Tuple, Dict, Any
from server.config import SessionConfigManager, DatabaseAccessLevel

logger = logging.getLogger(__name__)


class DatabaseScopeViolation(Exception):
    """数据库范围违规异常"""

    def __init__(self, message: str, violations: List[str]):
        super().__init__(message)
        self.violations = violations
        self.message = message


class DatabaseScopeChecker:
    """数据库范围检查器，支持多级访问控制和智能模式匹配"""

    # 系统数据库列表
    SYSTEM_DATABASES = {
        'information_schema',
        'mysql',
        'performance_schema',
        'sys'
    }

    # 跨数据库查询模式
    CROSS_DB_PATTERNS = [
        # database.table 格式
        r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # SHOW TABLES FROM database
        r'\bSHOW\s+(?:FULL\s+)?TABLES\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # USE database
        r'\bUSE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # SELECT ... FROM database.table
        r'\bFROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # JOIN database.table
        r'\bJOIN\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # INSERT INTO database.table
        r'\bINTO\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # UPDATE database.table
        r'\bUPDATE\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # DELETE FROM database.table
        r'\bDELETE\s+FROM\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # CREATE DATABASE
        r'\bCREATE\s+DATABASE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # DROP DATABASE
        r'\bDROP\s+DATABASE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b',
        # ALTER DATABASE
        r'\bALTER\s+DATABASE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b',
    ]

    # 特殊查询模式
    SPECIAL_QUERY_PATTERNS = {
        'SHOW_DATABASES': r'\bSHOW\s+DATABASES\b',
        'USE_STATEMENT': r'\bUSE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b',
        'SYSTEM_TABLE_ACCESS': [
            r'\bmysql\.user\b',
            r'\bmysql\.db\b',
            r'\binformation_schema\.',
            r'\bperformance_schema\.',
            r'\bsys\.'
        ]
    }

    def __init__(self, session_config: SessionConfigManager):
        """
        初始化数据库范围检查器

        Args:
            session_config: 会话配置管理器实例
        """
        self.session_config = session_config

        # 获取配置项（不加前缀）
        self.is_enabled = session_config.get('ENABLE_DATABASE_ISOLATION', False)
        self.allowed_database = session_config.get('MYSQL_DATABASE', '')

        # 获取数据库访问级别（字符串转换为枚举）
        access_level_str = session_config.get('DATABASE_ACCESS_LEVEL', 'permissive').lower()
        try:
            self.access_level = DatabaseAccessLevel(access_level_str)
        except ValueError:
            self.access_level = DatabaseAccessLevel.PERMISSIVE

        logger.info(f"数据库范围检查器初始化: 允许数据库={self.allowed_database}, "
                    f"访问级别={self.access_level.value}, 启用={self.is_enabled}")

    def check_query(self, sql_query: str) -> Tuple[bool, List[str]]:
        """
        检查SQL查询是否违反数据库范围限制

        Args:
            sql_query: SQL查询语句

        Returns:
            (是否允许, 违规详情列表)
        """
        if not self.is_enabled:
            return True, []

        violations = []

        # 提取查询中涉及的数据库
        referenced_databases = self._extract_databases(sql_query)

        # 检查每个引用的数据库
        for db_name in referenced_databases:
            if not self._is_database_allowed(db_name):
                violations.append(f"不允许访问数据库: {db_name}")

        # 检查特殊查询类型
        special_violations = self._check_special_queries(sql_query)
        violations.extend(special_violations)

        # 检查数据库创建/删除操作
        ddl_violations = self._check_ddl_operations(sql_query)
        violations.extend(ddl_violations)

        is_allowed = len(violations) == 0

        if violations:
            logger.warning(f"数据库范围检查失败: {violations}")

        return is_allowed, violations

    def enforce_query(self, sql_query: str) -> None:
        """
        强制执行数据库范围检查，如果违规则抛出异常

        Args:
            sql_query: SQL查询语句

        Raises:
            DatabaseScopeViolation: 如果查询违反数据库范围限制
        """
        is_allowed, violations = self.check_query(sql_query)
        if not is_allowed:
            raise DatabaseScopeViolation(
                f"数据库范围违规: {len(violations)}个问题",
                violations
            )

    def _extract_databases(self, sql_query: str) -> Set[str]:
        """提取SQL查询中涉及的数据库名称"""
        databases: Set[str] = set()
        normalized_sql = re.sub(r'\s+', ' ', sql_query.upper().strip())

        for pattern in self.CROSS_DB_PATTERNS:
            try:
                matches = re.finditer(pattern, normalized_sql, re.IGNORECASE)
                for match in matches:
                    # 处理匹配结果
                    if match.groups():
                        # 获取第一个捕获组（通常是数据库名）
                        db_name = match.group(1).lower()

                        # 验证数据库名称格式
                        if self._is_valid_database_name(db_name):
                            databases.add(db_name)
            except re.error as e:
                logger.warning(f"正则表达式错误: 模式={pattern}, 错误={str(e)}")

        return databases

    def _is_valid_database_name(self, name: str) -> bool:
        """检查是否是有效的数据库名称"""
        # 数据库名称规则：字母、数字、下划线，不能以数字开头
        return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name))

    def _is_database_allowed(self, db_name: str) -> bool:
        """检查数据库是否被允许访问"""
        db_name_lower = db_name.lower()

        # 检查是否是允许的主数据库
        if self.allowed_database and db_name_lower == self.allowed_database.lower():
            return True

        # 根据访问级别决定是否允许系统数据库
        if self.access_level == DatabaseAccessLevel.RESTRICTED:
            if db_name_lower in self.SYSTEM_DATABASES:
                return True

        return False

    def _check_special_queries(self, sql_query: str) -> List[str]:
        """检查特殊类型的查询"""
        violations = []
        normalized_sql = sql_query.upper().strip()

        # 检查SHOW DATABASES查询
        if re.search(self.SPECIAL_QUERY_PATTERNS['SHOW_DATABASES'], normalized_sql):
            if self.access_level == DatabaseAccessLevel.STRICT:
                violations.append("严格模式下不允许执行 SHOW DATABASES")

        # 检查USE语句
        use_match = re.search(self.SPECIAL_QUERY_PATTERNS['USE_STATEMENT'], normalized_sql)
        if use_match:
            db_name = use_match.group(1).lower()
            if not self._is_database_allowed(db_name):
                violations.append(f"不允许使用 USE 语句切换到数据库: {db_name}")

        # 检查系统表访问
        for pattern in self.SPECIAL_QUERY_PATTERNS['SYSTEM_TABLE_ACCESS']:
            if re.search(pattern, normalized_sql, re.IGNORECASE):
                if self.access_level == DatabaseAccessLevel.STRICT:
                    violations.append("严格模式下不允许访问系统表")
                    break

        return violations

    def _check_ddl_operations(self, sql_query: str) -> List[str]:
        """检查数据库DDL操作"""
        violations = []
        normalized_sql = sql_query.upper().strip()

        # 检查CREATE DATABASE
        create_match = re.search(r'\bCREATE\s+DATABASE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', normalized_sql)
        if create_match:
            if self.access_level != DatabaseAccessLevel.PERMISSIVE:
                violations.append("非宽松模式下不允许创建数据库")

        # 检查DROP DATABASE
        drop_match = re.search(r'\bDROP\s+DATABASE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', normalized_sql)
        if drop_match:
            db_name = drop_match.group(1).lower()
            if db_name == self.allowed_database.lower():
                violations.append("不允许删除当前使用的数据库")
            elif self.access_level != DatabaseAccessLevel.PERMISSIVE:
                violations.append("非宽松模式下不允许删除数据库")

        # 检查ALTER DATABASE
        alter_match = re.search(r'\bALTER\s+DATABASE\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', normalized_sql)
        if alter_match:
            db_name = alter_match.group(1).lower()
            if db_name != self.allowed_database.lower() and self.access_level != DatabaseAccessLevel.PERMISSIVE:
                violations.append("非宽松模式下不允许修改其他数据库")

        return violations

    def get_allowed_databases(self) -> Set[str]:
        """获取允许访问的数据库列表"""
        allowed = set()

        if self.allowed_database:
            allowed.add(self.allowed_database.lower())

        if self.access_level == DatabaseAccessLevel.RESTRICTED:
            allowed.update(self.SYSTEM_DATABASES)

        return allowed

    def is_cross_database_query(self, sql_query: str) -> bool:
        """检查是否是跨数据库查询"""
        referenced_dbs = self._extract_databases(sql_query)
        return len(referenced_dbs) > 1 or (
                len(referenced_dbs) == 1 and
                next(iter(referenced_dbs)) != self.allowed_database.lower()
        )

    def get_database_access_report(self, sql_query: str) -> Dict[str, Any]:
        """
        获取数据库访问的详细报告

        Args:
            sql_query: SQL查询语句

        Returns:
            dict: 包含数据库访问详细信息的字典
        """
        referenced_dbs = self._extract_databases(sql_query)
        allowed_dbs = self.get_allowed_databases()

        return {
            'query': sql_query,
            'referenced_databases': list(referenced_dbs),
            'allowed_databases': list(allowed_dbs),
            'is_cross_database': self.is_cross_database_query(sql_query),
            'violations': self.check_query(sql_query)[1],
            'access_level': self.access_level.value,
            'allowed_database': self.allowed_database,
            'is_enabled': self.is_enabled
        }
