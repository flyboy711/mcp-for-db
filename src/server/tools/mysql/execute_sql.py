import logging
from typing import Dict, Any, Sequence, List, Set, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re
import csv
from io import StringIO
from server.utils.logger import get_logger, configure_logger
from server.config.dbconfig import MySQLConfigManager
from server.config.database import mysql_pool_manager
from mcp import Tool
from mcp.types import TextContent
from server.tools.mysql.base import BaseHandler
from server.tools.mysql.exceptions import SQLPermissionError, SQLExecutionError
import aiomysql

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="execute_sql.log")

# 预编译常用正则表达式
COMMENT_PATTERN = re.compile(r'--.*$|/\*.*?\*/', re.MULTILINE | re.DOTALL)
HOSTNAME_PATTERN = re.compile(r'(?:https?:\/\/)?([a-zA-Z0-9\-\.]+)(?::\d+)?')


class SQLOperation(str, Enum):
    """SQL 操作类型枚举"""
    SELECT = 'SELECT'
    INSERT = 'INSERT'
    UPDATE = 'UPDATE'
    DELETE = 'DELETE'
    CREATE = 'CREATE'
    ALTER = 'ALTER'
    DROP = 'DROP'
    TRUNCATE = 'TRUNCATE'
    SHOW = 'SHOW'
    DESCRIBE = 'DESCRIBE'
    EXPLAIN = 'EXPLAIN'
    EXECUTE = 'EXECUTE'

    @classmethod
    def from_str(cls, value: str) -> 'SQLOperation':
        try:
            return cls(value.upper())
        except ValueError:
            raise ValueError(f"Unsupported SQL operation: {value}")


@dataclass
class SQLResult:
    """SQL 执行结果封装"""
    success: bool
    message: str
    columns: Optional[List[str]] = None
    rows: Optional[List[Tuple]] = None
    affected_rows: int = 0


class ExecuteSQL(BaseHandler):
    """安全可靠的 MySQL SQL 执行工具"""

    name = "sql_executor"
    description = "Execute SQL queries on MySQL database with enhanced security and performance"

    # SQL 操作检测模式（支持多行）
    OPERATION_PATTERNS = {
        SQLOperation.SELECT: re.compile(r'^\s*SELECT\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.INSERT: re.compile(r'^\s*INSERT\s+INTO\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.UPDATE: re.compile(r'^\s*UPDATE\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.DELETE: re.compile(r'^\s*DELETE\s+FROM\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.CREATE: re.compile(r'^\s*CREATE\s+(TABLE|VIEW|INDEX|DATABASE|PROCEDURE)\b',
                                        re.IGNORECASE | re.MULTILINE),
        SQLOperation.ALTER: re.compile(r'^\s*ALTER\s+(TABLE|DATABASE|PROCEDURE)\b',
                                       re.IGNORECASE | re.MULTILINE),
        SQLOperation.DROP: re.compile(r'^\s*DROP\s+(TABLE|VIEW|INDEX|DATABASE|PROCEDURE)\b',
                                      re.IGNORECASE | re.MULTILINE),
        SQLOperation.TRUNCATE: re.compile(r'^\s*TRUNCATE\s+TABLE\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.SHOW: re.compile(r'^\s*SHOW\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.DESCRIBE: re.compile(r'^\s*(DESCRIBE|DESC)\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.EXPLAIN: re.compile(r'^\s*EXPLAIN\b', re.IGNORECASE | re.MULTILINE),
        SQLOperation.EXECUTE: re.compile(r'^\s*(CALL|EXECUTE)\b', re.IGNORECASE | re.MULTILINE),
    }

    # 白名单安全字符
    SAFE_CHAR_PATTERN = re.compile(r'[^a-zA-Z0-9_\-\. ]')
    MAX_QUERY_LENGTH = 5000  # 限制最大查询长度
    MAX_RESULT_ROWS = 100  # 限制最大返回行数

    def __init__(self):
        self._config_manager = MySQLConfigManager()
        self._allowed_ops_cache = None  # 缓存权限检查结果
        self._last_permission_check = None

    def get_tool_description(self) -> Tool:
        """获取工具描述（添加安全警告）"""
        return Tool(
            name=self.name,
            description=f"{self.description}. WARNING: Only allow parameterized queries to prevent SQL injection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL statement to execute. Use ? for parameter placeholders."
                    }
                },
                "required": ["query"]
            }
        )

    def _get_allowed_operations(self) -> Set[SQLOperation]:
        """获取当前角色允许的操作（带缓存机制）"""
        # 如果配置未变化则使用缓存
        config = self._config_manager.get_config()
        current_role = config.get("role", "readonly")

        if (self._allowed_ops_cache and
                self._last_permission_check == current_role):
            return self._allowed_ops_cache

        # 获取权限并缓存
        permissions = self._config_manager.get_role_permissions(current_role)
        allowed_ops = {SQLOperation.from_str(op) for op in permissions}

        self._allowed_ops_cache = allowed_ops
        self._last_permission_check = current_role

        logger.debug(f"Allowed operations for role '{current_role}': {allowed_ops}")
        return allowed_ops

    def check_permissions(self, operations: Set[SQLOperation]) -> bool:
        """检查操作权限（带详细错误信息）"""
        allowed = self._get_allowed_operations()
        unauthorized = operations - allowed

        if unauthorized:
            # 构建详细的权限错误信息
            op_names = ', '.join(op.value for op in unauthorized)
            allowed_names = ', '.join(op.value for op in allowed)
            role = self._config_manager.get_config().get("role", "readonly")

            raise SQLPermissionError(
                f"Permission denied for operations: {op_names}. "
                f"Your role '{role}' only allows: {allowed_names or 'none'}"
            )
        return True

    @staticmethod
    def clean_sql(sql: str) -> str:
        """清理 SQL 语句（更高效的方法）"""
        # 移除注释
        sql = COMMENT_PATTERN.sub('', sql)
        # 压缩连续空格
        return ' '.join(sql.split())

    def sanitize_identifier(self, identifier: str) -> str:
        """安全处理表名/列名标识符"""
        # 替换潜在危险字符
        sanitized = self.SAFE_CHAR_PATTERN.sub('', identifier)
        # 限制长度
        return sanitized[:64]

    def extract_operations(self, sql: str) -> Set[SQLOperation]:
        """提取 SQL 语句中的操作类型（支持多语句）"""
        # 先清理 SQL
        clean_sql = self.clean_sql(sql)

        # 检查 SQL 长度限制
        if len(clean_sql) > self.MAX_QUERY_LENGTH:
            raise SQLExecutionError(f"Query exceeds maximum length of {self.MAX_QUERY_LENGTH} characters")

        operations = set()

        # 检测所有操作类型
        for op, pattern in self.OPERATION_PATTERNS.items():
            if pattern.search(clean_sql):
                operations.add(op)

        # 如果未检测到操作，则默认为 SELECT
        if not operations:
            operations.add(SQLOperation.SELECT)

        return operations

    def validate_sql_parameters(self, sql: str, params: list) -> None:
        """验证参数数量与占位符匹配"""
        # 计算占位符数量
        placeholder_count = sql.count('?')

        # 验证参数数量
        if len(params) != placeholder_count:
            raise SQLExecutionError(
                f"Parameter count mismatch. Expected {placeholder_count} placeholders, "
                f"got {len(params)} parameters"
            )

    def format_result(self, result: SQLResult) -> str:
        """使用 CSV 模块安全格式化结果"""
        if not result.success:
            return result.message

        output = StringIO()
        writer = csv.writer(output)

        # 添加标题行
        if result.columns:
            writer.writerow(result.columns)

        # 添加数据行
        if result.rows:
            for row in result.rows:
                # 将 None 转换为空字符串
                safe_row = ['' if v is None else str(v) for v in row]
                writer.writerow(safe_row)

        content = output.getvalue()
        output.close()

        return content

    async def execute_single_statement(
            self,
            conn: aiomysql.Connection,
            statement: str,
            params: Optional[tuple] = None
    ) -> SQLResult:
        """安全执行单条 SQL 语句"""
        try:
            # 验证 SQL 参数
            param_list = params or ()
            self.validate_sql_parameters(statement, list(param_list))

            # 检查操作权限
            operations = self.extract_operations(statement)
            self.check_permissions(operations)

            # 记录安全查询日志（避免记录敏感数据）
            log_data = {
                "operation": list(operations),
                "query_length": len(statement),
                "param_count": len(param_list),
                "param_types": [type(p).__name__ for p in param_list]
            }
            logger.info(f"Executing SQL: {log_data}")

            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # 执行参数化查询
                await cursor.execute(statement, param_list)

                if cursor.description:
                    # 获取有限结果集
                    rows = await cursor.fetchmany(self.MAX_RESULT_ROWS)
                    columns = [col[0] for col in cursor.description]

                    # 如果结果集超过限制，添加警告
                    warning = ""
                    if await cursor.fetchone():
                        warning = f" (Truncated to {self.MAX_RESULT_ROWS} rows)"

                    return SQLResult(
                        success=True,
                        message=f"Query executed successfully{warning}",
                        columns=columns,
                        rows=[tuple(row.values()) for row in rows]
                    )
                else:
                    # 获取更新行数
                    return SQLResult(
                        success=True,
                        message="Execution successful",
                        affected_rows=cursor.rowcount
                    )

        except aiomysql.Error as e:
            logger.error(f"SQL execution error: {e.args[0] if e.args else str(e)}")
            raise SQLExecutionError(f"Execution failed: {e.args[0] if e.args else str(e)}")

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行 SQL 工具主入口（增强安全性和错误处理）"""
        # 验证输入参数
        if "query" not in arguments:
            return [TextContent(type="text", text="Error: Missing query parameter")]

        query = arguments["query"].strip()
        parameters = arguments.get("parameters", [])
        results = []
        has_errors = False

        # 验证基本 SQL 安全
        if not self.is_sql_safe(query):
            return [TextContent(type="text", text="Error: Query contains potentially unsafe elements")]

        # 拆分多条 SQL 语句
        statements = [stmt.strip() for stmt in query.split(';') if stmt.strip()]

        # 验证多语句权限
        if len(statements) > 1:
            if SQLOperation.EXECUTE not in self._get_allowed_operations():
                return [TextContent(type="text",
                                    text="Error: Multi-statement execution requires EXECUTE permission")]

        try:
            # 获取数据库连接
            async for conn in mysql_pool_manager.get_connection():
                # 为每条语句分配参数
                for i, statement in enumerate(statements):
                    # 第一条语句使用所有参数（简化模型）
                    stmt_params = tuple(parameters) if i == 0 else ()

                    try:
                        result = await self.execute_single_statement(conn, statement, stmt_params)
                        results.append(self.format_result(result))
                    except (SQLPermissionError, SQLExecutionError) as e:
                        results.append(f"ERROR in statement {i + 1}: {str(e)}")
                        has_errors = True
                        logger.warning(f"SQL statement {i + 1} failed: {e}")
                    except Exception as e:
                        results.append(f"CRITICAL ERROR in statement {i + 1}: {str(e)}")
                        has_errors = True
                        logger.exception(f"Unexpected error in SQL statement {i + 1}")

                # 添加执行摘要
                summary = f"Executed {len(statements)} statements with {len(has_errors and 'errors' or 'success')}"
                results.append(summary)

                return [TextContent(type="text", text="\n---\n".join(results))]

        except aiomysql.Error as e:
            error_msg = f"Database connection error: {str(e)}"
            logger.error(error_msg)
            return [TextContent(type="text", text=error_msg)]
        except Exception as e:
            error_msg = f"System error: {str(e)}"
            logger.exception(error_msg)
            return [TextContent(type="text", text=error_msg)]

    def is_sql_safe(self, sql: str) -> bool:
        """基础 SQL 安全检查（非完全防护，需配合参数化使用）"""
        # 1. 检查危险关键词组合
        dangerous_patterns = [
            r"DROP\s+DATABASE",
            r"TRUNCATE\s+TABLE",
            r";\s*DROP",
            r"EXEC\s*\(.+\)",
            r"UNION\s+SELECT",
            r"1=1;?\s*--"
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, sql, re.IGNORECASE):
                logger.warning(f"Potential dangerous pattern detected: {pattern}")
                return False

        # 2. 检查非参数化数据值
        if "'" in sql or '"' in sql or "--" in sql:
            # 允许在参数化查询中使用占位符
            if '?' not in sql:
                logger.warning("Potential unsafe literals without placeholders")
                return False

        return True
