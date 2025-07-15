import logging
from typing import Dict, Any, Sequence, List, Optional, Tuple, Union, AsyncGenerator
from dataclasses import dataclass
from enum import Enum
import re
import csv
from io import StringIO

from server.utils.logger import get_logger, configure_logger
from server.config import AppConfigManager
from server.config.database import DatabaseManager
from server.security.sql_interceptor import SQLInterceptor, SecurityException
from server.security.sql_parser import SQLParser
from server.security.sql_analyzer import SQLRiskAnalyzer
from server.security.db_scope_check import DatabaseScopeChecker, DatabaseScopeViolation
from mcp import Tool
from mcp.types import TextContent
from server.tools.mysql.base import BaseHandler

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="execute_sql.log")


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
    row_count: int = 0
    execution_time: float = 0.0


class ExecuteSQL(BaseHandler):
    """安全可靠的 MySQL SQL 执行工具，集成全面的安全检查"""

    name = "sql_executor"
    description = "Execute SQL queries on MySQL database with enhanced security and performance"

    def __init__(self):
        self.config_manager = AppConfigManager()
        self.database_manager = DatabaseManager(self.config_manager)
        self.sql_interceptor = SQLInterceptor(self.config_manager)
        self.sql_parser = SQLParser(self.config_manager)
        self.risk_analyzer = SQLRiskAnalyzer(self.config_manager)

        # 初始化数据库范围检查器
        self.database_checker = None
        if self.config_manager.ENABLE_DATABASE_ISOLATION:
            self.database_checker = DatabaseScopeChecker(self.config_manager)

        logger.info("SQL执行工具初始化完成")

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
                    },
                    "parameters": {
                        "type": "array",
                        "description": "List of parameters for parameterized queries",
                        "items": {"type": "string"}
                    },
                    "stream_results": {
                        "type": "boolean",
                        "description": "Whether to stream results for large queries",
                        "default": False
                    },
                    "batch_size": {
                        "type": "integer",
                        "description": "Batch size for streaming results",
                        "default": 1000
                    }
                },
                "required": ["query"]
            }
        )

    async def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None,
                            stream_results: bool = False, batch_size: int = 1000) -> Union[
        List[Dict[str, Any]], AsyncGenerator[List[Dict[str, Any]], None]]:
        """
        执行SQL查询，包含全面的安全检查和范围控制

        Args:
            query: SQL查询语句
            params: 查询参数 (可选)
            stream_results: 是否使用流式处理获取大型结果集
            batch_size: 流式处理的批次大小

        Returns:
            查询结果列表或结果生成器

        Raises:
            SecurityException: 当操作被安全机制拒绝时
            DatabaseScopeViolation: 当违反数据库范围限制时
            DatabasePermissionError: 当用户没有执行操作的权限时
        """
        try:
            # 安全检查
            await self.sql_interceptor.check_operation(query)

            # 数据库范围检查
            if self.database_checker:
                self.database_checker.enforce_query(query)

            # 执行查询
            return await self.database_manager.execute_query(
                query,
                params=params,
                stream_results=stream_results,
                batch_size=batch_size
            )
        except SecurityException as se:
            logger.error(f"安全拦截: {se.message}")
            raise
        except DatabaseScopeViolation as dve:
            logger.error(f"数据库范围违规: {dve.message}")
            for violation in dve.violations:
                logger.error(f" - {violation}")
            raise
        except Exception as e:
            logger.exception(f"查询执行失败: {str(e)}")
            raise

    def format_result(self, result: Union[List[Dict[str, Any]], Dict[str, Any]]) -> str:
        """使用 CSV 模块安全格式化结果"""
        if isinstance(result, dict):
            # 处理单个结果（如DML操作）
            return f"操作: {result.get('operation', 'UNKNOWN')}, 影响行数: {result.get('affected_rows', 0)}"

        if not result:
            return "无结果"

        # 尝试提取列名
        columns = []
        if result and isinstance(result[0], dict):
            columns = list(result[0].keys())

        output = StringIO()
        writer = csv.writer(output)

        # 添加标题行
        if columns:
            writer.writerow(columns)

        # 添加数据行
        for row in result:
            if isinstance(row, dict):
                # 将字典转换为元组，按列顺序
                row_values = [row.get(col, '') for col in columns]
                writer.writerow(row_values)
            elif isinstance(row, (list, tuple)):
                writer.writerow(row)
            else:
                writer.writerow([str(row)])

        content = output.getvalue()
        output.close()

        return content

    async def run_tool(self, arguments: Dict[str, Any]) -> Sequence[TextContent]:
        """执行 SQL 工具主入口（增强安全性和错误处理）"""
        # 验证输入参数
        if "query" not in arguments:
            return [TextContent(type="text", text="错误: 缺少查询参数")]

        query = arguments["query"].strip()
        parameters = arguments.get("parameters", [])
        stream_results = arguments.get("stream_results", False)
        batch_size = arguments.get("batch_size", 1000)

        # 参数处理
        params_dict = None
        if parameters:
            # 将参数列表转换为字典（假设参数按顺序提供）
            try:
                params_dict = {f"param_{i}": value for i, value in enumerate(parameters)}
            except Exception:
                logger.warning("参数格式无效，将忽略参数")

        try:
            # 执行查询
            if stream_results:
                # 流式处理结果
                results = []
                async for batch in self.execute_query(
                        query,
                        params=params_dict,
                        stream_results=True,
                        batch_size=batch_size
                ):
                    formatted_batch = self.format_result(batch)
                    results.append(TextContent(type="text", text=formatted_batch))

                # 添加摘要
                results.append(TextContent(type="text", text="\n---\n流式查询完成"))
                return results
            else:
                # 普通查询
                result = await self.execute_query(query, params=params_dict)
                formatted_result = self.format_result(result)
                return [TextContent(type="text", text=formatted_result)]

        except SecurityException as se:
            return [TextContent(type="text", text=f"安全拦截: {se.message}")]
        except DatabaseScopeViolation as dve:
            violations = "\n".join(dve.violations)
            return [TextContent(type="text", text=f"数据库范围违规: {dve.message}\n{violations}")]
        except Exception as e:
            logger.exception(f"SQL执行失败: {str(e)}")
            return [TextContent(type="text", text=f"执行失败: {str(e)}")]

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
                logger.warning(f"检测到潜在危险模式: {pattern}")
                return False

        # 2. 检查非参数化数据值
        if "'" in sql or '"' in sql or "--" in sql:
            # 允许在参数化查询中使用占位符
            if '?' not in sql:
                logger.warning("检测到未使用参数化查询的字符串字面量")
                return False

        return True

    async def execute_transaction(self, queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        在事务中执行多个查询

        Args:
            queries: 查询列表，每个元素是包含 'query' 和可选 'params' 的字典

        Returns:
            每个查询的结果列表
        """
        try:
            # 安全检查每个查询
            for query_item in queries:
                sql = query_item['query']
                await self.sql_interceptor.check_operation(sql)
                if self.database_checker:
                    self.database_checker.enforce_query(sql)

            # 执行事务
            return await self.database_manager.execute_transaction(queries)
        except SecurityException as se:
            logger.error(f"事务安全拦截: {se.message}")
            raise
        except DatabaseScopeViolation as dve:
            logger.error(f"事务数据库范围违规: {dve.message}")
            for violation in dve.violations:
                logger.error(f" - {violation}")
            raise
        except Exception as e:
            logger.exception(f"事务执行失败: {str(e)}")
            raise

    async def get_current_database(self) -> str:
        """获取当前连接的数据库名称"""
        return await self.database_manager.get_current_database()

    async def get_database_info(self) -> Dict[str, Any]:
        """获取数据库信息"""
        return await self.database_manager.get_database_info()


# 测试函数
async def test_sql_executor():
    """测试SQL执行工具"""
    executor = ExecuteSQL()

    # 测试简单查询
    print("测试简单查询:")
    result = await executor.execute_query("SELECT VERSION() AS version")
    print(f"数据库版本: {result[0]['version']}")

    # 测试安全拦截
    print("\n测试安全拦截:")
    try:
        await executor.execute_query("DROP TABLE important_table")
    except SecurityException as se:
        print(f"✅ 安全拦截成功: {se.message}")

    # 测试数据库范围检查
    print("\n测试数据库范围检查:")
    if executor.config_manager.ENABLE_DATABASE_ISOLATION:
        try:
            await executor.execute_query("SELECT * FROM other_db.users")
        except DatabaseScopeViolation as dve:
            print(f"✅ 数据库范围检查成功: {dve.message}")

    # 测试流式查询
    print("\n测试流式查询:")
    try:
        async for batch in executor.execute_query(
                "SELECT * FROM large_table",
                stream_results=True,
                batch_size=100
        ):
            print(f"获取到 {len(batch)} 条记录")
    except Exception as e:
        print(f"流式查询失败: {str(e)}")

    # 测试事务
    print("\n测试事务:")
    try:
        queries = [
            {"query": "INSERT INTO test (name) VALUES ('test1')"},
            {"query": "UPDATE test SET name = 'updated' WHERE name = 'test1'"}
        ]
        results = await executor.execute_transaction(queries)
        print(f"事务执行结果: {results}")
    except Exception as e:
        print(f"事务执行失败: {str(e)}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_sql_executor())
