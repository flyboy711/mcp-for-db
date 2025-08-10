import weakref
import aiomysql
import asyncio
import hashlib
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, Dict, Any, List, Union
from enum import Enum

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.server_mysql.config import SessionConfigManager
from mcp_for_db.server.shared.security.sql_interceptor import SQLInterceptor, SecurityException
from mcp_for_db.server.shared.security import SQLParser
from mcp_for_db.server.shared.security.sql_analyzer import SQLRiskAnalyzer
from mcp_for_db.server.shared.security.db_scope_check import DatabaseScopeChecker, DatabaseScopeViolation
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="mcp_database.log")
logger.setLevel(LOG_LEVEL)


class DatabaseConnectionState(Enum):
    """数据库连接状态枚举"""
    UNINITIALIZED = 0
    ACTIVE = 1
    CLOSED = 2
    ERROR = 3
    RECONNECTING = 4


class DatabasePermissionError(Exception):
    """数据库权限错误"""

    def __init__(self, message: str, operation: str, table: str):
        super().__init__(message)
        self.operation = operation
        self.table = table
        self.message = message


class DatabaseManager:
    """数据库管理器，集成连接池、安全检查和范围控制"""
    # 跟踪所有实例
    _all_instances = weakref.WeakSet()

    def __init__(self, session_config: SessionConfigManager):
        """
        初始化数据库管理器

        Args:
            session_config: 会话配置管理器实例
        """
        self.session_config = session_config
        self._pool = None
        self._state = DatabaseConnectionState.UNINITIALIZED
        self._config_hash = None
        self._successful_auth_plugin = None
        self._last_connection_time = 0
        self._reconnect_attempts = 0

        # 初始化安全组件
        self.sql_parser = SQLParser(session_config)
        self.risk_analyzer = SQLRiskAnalyzer(session_config)
        self.sql_interceptor = SQLInterceptor(session_config)

        # 初始化数据库范围检查器
        self.database_checker = None
        if session_config.get('MYSQL_ENABLE_DATABASE_ISOLATION', False):
            self.database_checker = DatabaseScopeChecker(session_config)

        # 添加到实例集合
        DatabaseManager._all_instances.add(self)
        logger.info("数据库管理器初始化完成")

    @classmethod
    async def close_all_instances(cls):
        """关闭所有数据库管理器实例的连接池"""
        logger.info("关闭所有数据库连接池...")
        for instance in list(cls._all_instances):
            try:
                await instance.close_pool()
            except Exception as e:
                logger.error(f"关闭数据库连接池失败: {str(e)}")

    async def close_pool(self) -> None:
        """安全关闭数据库连接池"""
        if not self._pool or self._state in (DatabaseConnectionState.CLOSED, DatabaseConnectionState.UNINITIALIZED):
            return

        logger.info("关闭数据库连接池...")
        try:
            # 检查事件循环状态
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    # 正常关闭流程
                    self._pool.close()
                    await self._pool.wait_closed()
                    logger.info("连接池已安全关闭")
                    self._state = DatabaseConnectionState.CLOSED
                    return
            except RuntimeError:
                # 事件循环未运行或已关闭
                pass

            # 事件循环不可用时直接关闭
            self._pool.close()
            logger.warning("连接池被强制关闭（事件循环不可用）")
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                logger.warning("事件循环已关闭，直接关闭连接池")
                self._pool.close()
            else:
                logger.warning(f"连接池关闭时发生运行时错误: {str(e)}")
        except asyncio.CancelledError:
            logger.warning("连接池关闭操作被取消")
        except Exception as e:
            logger.exception(f"关闭连接池时出错: {str(e)}")
        finally:
            self._pool = None
            self._state = DatabaseConnectionState.CLOSED

    @property
    def state(self) -> DatabaseConnectionState:
        """返回当前连接池状态"""
        return self._state

    async def ensure_pool(self) -> None:
        """确保连接池已初始化并可用"""
        if self._state in (DatabaseConnectionState.ACTIVE, DatabaseConnectionState.ERROR):
            return

        if self._state in (DatabaseConnectionState.UNINITIALIZED, DatabaseConnectionState.CLOSED):
            await self.initialize_pool()

    async def initialize_pool(self, max_retries: int = 3) -> None:
        """
        初始化或重置数据库连接池

        Args:
            max_retries: 最大重试次数
        """
        # 关闭现有连接池
        await self.close_pool()

        logger.info("初始化数据库连接池...")

        # 计算当前配置哈希
        current_config = self.get_current_config()
        new_hash = self._compute_config_hash(current_config)

        # 如果配置变更，更新内部状态
        if new_hash != self._config_hash:
            self._config_hash = new_hash
            logger.info("检测到配置变更，使用新配置初始化连接池")

        # 构建连接参数
        connection_params = self._build_connection_params()

        # 记录安全的配置信息（不含密码）
        safe_config = {k: v for k, v in connection_params.items() if k != "password"}
        logger.debug(f"连接参数: {safe_config}")

        try:
            # 首次尝试连接
            self._pool = await aiomysql.create_pool(**connection_params)
            logger.info("数据库连接池初始化成功")
            self._state = DatabaseConnectionState.ACTIVE
            self._last_connection_time = time.time()
            self._reconnect_attempts = 0
            return
        except aiomysql.OperationalError as e:
            error_msg = str(e).lower()
            logger.warning(f"数据库连接异常: {e}")

            # 如果是认证问题且设置了重试，则尝试不同认证方式
            if "plugin" in error_msg and max_retries > 0:
                logger.info("尝试备用认证方案...")
                await self._try_alternative_auth(connection_params, max_retries)
            else:
                self._state = DatabaseConnectionState.ERROR
                self._handle_connection_error(e)
                raise
        except Exception as e:
            logger.exception(f"数据库连接池初始化失败: {e}")
            self._state = DatabaseConnectionState.ERROR
            self._handle_connection_error(e)
            raise

    def get_current_config(self) -> Dict[str, Any]:
        """获取当前配置字典"""
        return {
            # 数据库配置
            "host": self.session_config.get("MYSQL_HOST", "localhost"),
            "port": self.session_config.get("MYSQL_PORT", "13308"),
            "user": self.session_config.get("MYSQL_USER", "videx"),
            "password": self.session_config.get("MYSQL_PASSWORD", "password"),
            "database": self.session_config.get("MYSQL_DATABASE", "tpch_tiny"),
            "DB_AUTH_PLUGIN": self.session_config.get("MYSQL_DB_AUTH_PLUGIN"),
            "DB_CONNECTION_TIMEOUT": self.session_config.get("MYSQL_DB_CONNECTION_TIMEOUT", 5),

            # 连接池配置
            "DB_POOL_MIN_SIZE": self.session_config.get("MYSQL_DB_POOL_MIN_SIZE", 5),
            "DB_POOL_MAX_SIZE": self.session_config.get("MYSQL_DB_POOL_MAX_SIZE", 20),
        }

    def _compute_config_hash(self, config: Dict[str, Any]) -> str:
        """计算配置哈希值用于标识配置变更"""
        return hashlib.md5(str(config).encode('utf-8')).hexdigest()

    def _build_connection_params(self) -> Dict[str, Any]:
        """构建连接参数"""
        return {
            "host": self.session_config.get("MYSQL_HOST"),
            "port": int(self.session_config.get("MYSQL_PORT")),
            "user": self.session_config.get("MYSQL_USER"),
            "password": self.session_config.get("MYSQL_PASSWORD"),
            "db": self.session_config.get("MYSQL_DATABASE"),
            "autocommit": True,
            "minsize": self.session_config.get("MYSQL_DB_POOL_MIN_SIZE", 5),
            "maxsize": self.session_config.get("MYSQL_DB_POOL_MAX_SIZE", 20),
            "charset": "utf8mb4",
            "cursorclass": aiomysql.DictCursor,
            "connect_timeout": self.session_config.get("MYSQL_DB_CONNECTION_TIMEOUT", 5),
            "auth_plugin": self._successful_auth_plugin or self.session_config.get("MYSQL_DB_AUTH_PLUGIN",
                                                                                   "mysql_native_password")
        }

    async def _try_alternative_auth(self, params: Dict[str, Any], max_retries: int) -> None:
        """尝试不同的认证方式"""
        plugins = [
            None,  # 自动协商
            "mysql_native_password",
            "caching_sha2_password",
            "sha256_password"
        ]

        for plugin in plugins:
            try:
                # 更新认证插件参数
                new_params = params.copy()
                if plugin:
                    new_params["auth_plugin"] = plugin
                elif "auth_plugin" in new_params:
                    del new_params["auth_plugin"]

                logger.info(f"尝试认证插件: {plugin or 'auto'}")
                self._pool = await aiomysql.create_pool(**new_params)

                logger.info(f"使用插件 {plugin or 'auto'} 连接成功")
                self._state = DatabaseConnectionState.ACTIVE
                self._successful_auth_plugin = plugin
                self._last_connection_time = time.time()
                self._reconnect_attempts = 0

                # 如果成功使用特定插件，更新会话配置
                if plugin:
                    self.session_config.update({"MYSQL_DB_AUTH_PLUGIN": plugin})
                return
            except Exception as e:
                logger.warning(f"插件 {plugin} 失败: {str(e)}")
                max_retries -= 1
                if max_retries <= 0:
                    break

        logger.critical("所有认证方式尝试失败")
        self._state = DatabaseConnectionState.ERROR
        raise ConnectionError("无法连接数据库，请检查服务器配置")

    def _handle_connection_error(self, error: Exception) -> None:
        """处理连接错误"""
        error_msg = str(error).lower()

        # 根据错误类型提供更具体的建议
        if "access denied" in error_msg:
            logger.error("访问被拒绝，请检查用户名和密码")
        elif "unknown database" in error_msg:
            db_name = self.session_config.get("MYSQL_DATABASE")
            logger.error(f"数据库 '{db_name}' 不存在")
        elif "can't connect" in error_msg or "connection refused" in error_msg:
            logger.error("无法连接到MySQL服务器，请检查服务是否启动")
        elif "authentication plugin" in error_msg:
            current_auth = self.session_config.get("MYSQL_DB_AUTH_PLUGIN")
            logger.error(f"认证插件问题: {error_msg}")
            if current_auth == 'caching_sha2_password':
                logger.error("解决方案:")
                logger.error("1. 确保已安装 cryptography 包: pip install cryptography")
                logger.error("2. 或者修改用户认证方式为 mysql_native_password")
                logger.error(f"3. 在配置中设置 DB_AUTH_PLUGIN=mysql_native_password")

        # 增加重连尝试计数
        self._reconnect_attempts += 1

        # 如果重连次数过多，记录警告
        if self._reconnect_attempts > 3:
            logger.warning("数据库连接失败次数过多，请检查数据库配置和服务状态")

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiomysql.Connection, None]:
        """
        获取数据库连接的异步上下文管理器

        Yields:
            aiomysql.Connection: 数据库连接对象
        """
        # 确保连接池可用
        await self.ensure_pool()

        # 检查配置是否变更
        current_config = self.get_current_config()
        current_hash = self._compute_config_hash(current_config)

        if current_hash != self._config_hash and self._state == DatabaseConnectionState.ACTIVE:
            logger.warning("数据库配置已变更，正在重建连接池...")
            await self.initialize_pool()

        # 确保连接池不为空
        if not self._pool or self._state != DatabaseConnectionState.ACTIVE:
            raise RuntimeError("数据库连接池不可用")

        try:
            # 获取连接
            async with self._pool.acquire() as conn:
                # === 实际执行操作前的安全拦截 ===
                async def safe_cursor():
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        # 安全层: 阻止高危操作执行
                        def execute_wrapper(query, params=None):
                            # 解析SQL以获取操作类型和表名
                            parsed_sql = self.sql_parser.parse_query(query)
                            operation = parsed_sql['operation_type'].upper()

                            # 硬阻止高危操作
                            if operation in {'DROP', 'TRUNCATE', 'ALTER', 'RENAME', 'LOCK', "DELETE"}:
                                raise SecurityException(f"高危操作 {operation} 被强制阻止")

                            # 执行原始操作
                            if params:
                                return cursor.execute(query, params)
                            return cursor.execute(query)

                        # 替换原执行方法
                        cursor.execute = execute_wrapper
                        yield cursor

                # 返回安全包装后的连接
                conn.safe_cursor = safe_cursor
                yield conn
        except aiomysql.Error as e:
            logger.error(f"获取数据库连接失败: {str(e)}")
            self._handle_connection_error(e)
            raise
        except Exception as e:
            logger.exception(f"获取数据库连接时发生未预期错误: {str(e)}")
            raise

    ###################################################################################################################
    ###################################################################################################################
    ###################################################################################################################
    ###################################################################################################################
    async def execute_query(self, sql_query: str, params: Optional[Dict[str, Any]] = None,
                            require_database: bool = True) -> Union[
        List[Dict[str, Any]], AsyncGenerator[List[Dict[str, Any]], None]]:
        """
        执行SQL查询，包含全面的安全检查和范围控制

        Args:
            sql_query: SQL查询语句
            params: 查询参数 (可选)
            require_database: 是否要求指定数据库

        Returns:
            查询结果列表或结果生成器

        Raises:
            SecurityException: 当操作被安全机制拒绝时
            DatabaseScopeViolation: 当违反数据库范围限制时
            DatabasePermissionError: 当用户没有执行操作的权限时
        """
        start_time = time.time()

        try:
            # === 提前拦截高危操作 ===
            # 解析SQL以获取操作类型
            parsed_sql = self.sql_parser.parse_query(sql_query)
            operation = parsed_sql['operation_type']

            # 硬阻止高危操作
            HARD_BLOCK_OPS = {'DROP', 'TRUNCATE', 'ALTER', 'RENAME', 'LOCK', 'DELETE', 'UPDATE'}
            if operation in HARD_BLOCK_OPS:
                raise SecurityException(f"高危操作 {operation} 被强制阻止 - 此操作不可执行")

            # 安全检查
            await self.sql_interceptor.check_operation(sql_query)

            # 数据库范围检查
            if self.database_checker:
                self.database_checker.enforce_query(sql_query)

            # 解析SQL以获取操作类型和表名
            category = parsed_sql['category']

            async with self.get_connection() as conn:
                # 创建游标
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 执行查询
                    if params:
                        await cursor.execute(sql_query, params)
                    else:
                        await cursor.execute(sql_query)

                    # 处理结果
                    if cursor.description:
                        # SELECT查询，获取结果
                        # 一次性获取所有结果
                        results = await cursor.fetchall()
                        return self._process_results(results, sql_query, operation, category)
                    else:
                        # DML/DDL操作，返回影响行数
                        affected_rows = cursor.rowcount
                        # 对于修改操作，提交事务
                        if category == 'DML' and operation in {'UPDATE', 'DELETE', 'INSERT'}:
                            await conn.commit()

                        return self._process_dml_result(affected_rows, sql_query, operation)
        except aiomysql.OperationalError as e:
            # 处理权限错误
            error_code = e.args[0] if e.args else 0
            if error_code in (1142, 1044, 1045):  # 常见的权限错误代码
                parsed_sql = self.sql_parser.parse_query(sql_query)
                raise DatabasePermissionError(
                    f"数据库权限错误: {str(e)}",
                    parsed_sql['operation_type'],
                    ", ".join(parsed_sql['tables'])
                )
            else:
                logger.exception(f"查询执行失败: {str(e)}")
                raise
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
        finally:
            # 记录查询性能
            execution_time = time.time() - start_time
            self._log_query_performance(sql_query, execution_time)

    ###################################################################################################################
    ###################################################################################################################
    ###################################################################################################################
    def _enhance_metadata_results(self, results: List[Dict[str, Any]], operation: str) -> List[Dict[str, Any]]:
        """
        增强元数据查询结果

        Args:
            results: 原始结果列表
            operation: 操作类型

        Returns:
            增强后的结果列表
        """
        enhanced = []
        for row in results:
            row_dict = dict(row)

            # 对特定元数据查询进行增强
            if operation == 'SHOW':
                # 检查是否是 SHOW TABLES 结果
                for key in list(row_dict.keys()):
                    if key.startswith('Tables_in_'):
                        # 添加统一的 table_name 字段
                        row_dict['table_name'] = row_dict[key]
                        # 保留原始字段
                        row_dict['database'] = key.replace('Tables_in_', '')
                        break
            elif operation in {'DESC', 'DESCRIBE'} and 'Field' in row_dict:
                # DESC/DESCRIBE 表结构结果增强
                row_dict['column_name'] = row_dict['Field']
                row_dict['data_type'] = row_dict['Type']

            enhanced.append(row_dict)
        return enhanced

    def _process_results(self, results: List[Dict[str, Any]], sql_query: str,
                         operation: str, category: str) -> List[Dict[str, Any]]:
        """
        处理查询结果

        Args:
            results: 原始结果
            sql_query: SQL查询语句
            operation: 操作类型
            category: 操作类别

        Returns:
            处理后的结果列表
        """
        # 对于元数据查询，增强结果
        if category == 'METADATA':
            return self._enhance_metadata_results(results, operation)

        # 对于空结果集，添加元信息
        if not results:
            return [{'operation': operation, 'result_count': 0}]

        return [dict(row) for row in results]

    def _process_dml_result(self, affected_rows: int, sql_query: str, operation: str) -> List[Dict[str, Any]]:
        """
        处理DML操作结果

        Args:
            affected_rows: 影响行数
            sql_query: SQL查询语句
            operation: 操作类型

        Returns:
            结果字典列表
        """
        logger.debug(f"{operation} 操作影响了 {affected_rows} 行数据")
        return [{"operation": operation, "affected_rows": affected_rows}]

    async def execute_transaction(self, queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        在事务中执行多个查询

        Args:
            queries: 查询列表，每个元素是包含 'query' 和可选 'params' 的字典

        Returns:
            每个查询的结果列表
        """
        results = []
        async with self.get_connection() as conn:
            try:
                # 开始事务
                await conn.begin()

                for query_item in queries:
                    sql = query_item['query']
                    params = query_item.get('params')

                    # 执行单个查询
                    result = await self.execute_query(sql, params)
                    results.append(result)

                # 提交事务
                await conn.commit()
                return results
            except Exception:
                # 回滚事务
                await conn.rollback()
                logger.error("事务执行失败，已回滚")
                raise

    def _log_query_performance(self, query: str, execution_time: float):
        """记录查询性能日志"""
        # 截断长查询以避免日志过大
        truncated_query = query[:150] + '...' if len(query) > 150 else query

        # 解析操作类型
        try:
            parsed = self.sql_parser.parse_query(query)
            operation = parsed.get('operation_type', 'UNKNOWN')
        except RuntimeError:
            operation = 'UNKNOWN'

        # 根据执行时间确定日志级别
        if execution_time >= 1.0:  # 超过1秒的查询记录为警告
            logger.warning(f"慢查询 [{operation}]: {truncated_query} 执行时间: {execution_time:.4f}秒")
        elif execution_time >= 0.5:  # 超过0.5秒的查询记录为提醒
            logger.info(f"较慢查询 [{operation}]: {truncated_query} 执行时间: {execution_time:.4f}秒")
        else:
            logger.debug(f"查询 [{operation}] 执行时间: {execution_time:.4f}秒")

    def is_healthy(self) -> bool:
        """检查连接池是否健康"""
        return self._state == DatabaseConnectionState.ACTIVE and self._pool is not None

    async def reconnect(self) -> None:
        """尝试重新连接数据库"""
        if self._state != DatabaseConnectionState.ERROR:
            return

        logger.info("尝试重新连接数据库...")
        self._state = DatabaseConnectionState.RECONNECTING

        try:
            await self.initialize_pool()
            logger.info("数据库重新连接成功")
        except Exception as e:
            logger.error(f"数据库重新连接失败: {str(e)}")
            self._state = DatabaseConnectionState.ERROR

    async def get_database_info(self) -> Dict[str, Any]:
        """获取数据库信息"""
        try:
            result = await self.execute_query("SELECT VERSION() AS version")
            version = result[0]['version'] if result else "Unknown"

            return {
                "version": version,
                "status": self._state.name,
                "last_connection": self._last_connection_time,
                "reconnect_attempts": self._reconnect_attempts
            }
        except Exception as e:
            logger.error(f"获取数据库信息失败: {str(e)}")
            return {
                "error": str(e),
                "status": self._state.name
            }

    async def get_current_database(self) -> str:
        """
        获取当前连接的数据库名称

        Returns:
            当前数据库名称，如果未设置则返回空字符串
        """
        try:
            result = await self.execute_query("SELECT DATABASE() AS db", require_database=False)
            if result and 'db' in result[0]:
                return result[0]['db'] or ""
            return ""
        except Exception as e:
            logger.error(f"获取当前数据库名称失败: {str(e)}")
            return ""


# 测试代码
async def test_database_operations():
    """测试数据库操作"""
    logger.info("\n=== 启动数据库操作测试 ===")

    # 创建会话配置管理器
    session_config = SessionConfigManager({
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    })

    # 创建数据库管理器实例
    database_manager = DatabaseManager(session_config)

    try:
        # 场景1: 获取数据库信息
        logger.info("测试场景1: 获取数据库信息")
        db_info = await database_manager.get_database_info()
        logger.info(f"数据库信息: {db_info}")

        # 场景2: 获取当前数据库名称
        logger.info("\n测试场景2: 获取当前数据库名称")
        current_db = await database_manager.get_current_database()
        logger.info(f"当前数据库: {current_db}")

        # 场景3: 执行简单查询
        logger.info("\n测试场景3: 执行简单查询")
        result = await database_manager.execute_query("SELECT VERSION() AS version")
        logger.info(f"数据库版本: {result[0]['version']}")

        # 场景4: 测试元数据查询增强
        logger.info("\n测试场景4: 测试元数据查询增强")
        result = await database_manager.execute_query("SHOW TABLES")
        logger.info(f"当前数据库中所有的表：{result}")
        for row in result:
            logger.info(f"表名: {row.get('table_name', row.get('Tables_in_test', '未知'))}")

        # # 场景6: 测试DML操作
        # logger.info("\n测试场景6: 测试DML操作")
        # try:
        #     result = await database_manager.execute_query("INSERT INTO orders (O_ORDERSTATUS) VALUES ('test1')")
        #     logger.info(f"插入操作结果: {result}")
        # except DatabasePermissionError as dpe:
        #     logger.info(f"权限错误处理成功: {dpe.message}")
        #     logger.info(f"操作: {dpe.operation}, 表: {dpe.table}")

        # 场景7: 测试安全拦截
        logger.info("\n测试场景7: 测试安全拦截")
        try:
            await database_manager.execute_query("DROP TABLE t_users")
        except SecurityException as se:
            logger.info(f"安全拦截成功: {se.message}")

        # 场景8: 测试连接恢复
        logger.info("\n测试场景9: 测试连接恢复")
        # 模拟连接失败
        database_manager._state = DatabaseConnectionState.ERROR
        await database_manager.reconnect()
        db_info = await database_manager.get_database_info()
        logger.info(f"重新连接后数据库状态: {db_info['status']}")

    except Exception as e:
        logger.exception(f"测试失败: {str(e)}")
    finally:
        # 清理
        await database_manager.close_pool()
        logger.info("=== 测试完成 ===")


async def main():
    # 创建会话配置管理器
    session_config = SessionConfigManager({
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    })

    # 创建数据库管理器实例
    database_manager = DatabaseManager(session_config)

    try:
        # 获取当前数据库名称
        current_db = await database_manager.get_current_database()
        print(f"当前数据库: {current_db}")

        # 执行元数据查询
        tables = await database_manager.execute_query("SHOW TABLES")
        for table in tables:
            # 使用增强后的 table_name 字段
            table_name = table.get('table_name', table.get('Tables_in_' + current_db.lower(), '未知表名'))
            print(f"表名: {table_name}")

        print(f"当前执行计划结果:{await database_manager.execute_query("explain  select * from orders")}")

        result = await database_manager.execute_query(f"SELECT * FROM t_users WHERE age > %(age1)s and age<%(age2)s", {
            "age1": 25, "age2": 26})

        print(result)
    finally:
        await database_manager.close_pool()


if __name__ == "__main__":
    asyncio.run(test_database_operations())
    # asyncio.run(main())
