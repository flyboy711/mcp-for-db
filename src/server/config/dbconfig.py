import os
from typing import List, Set, Any
from enum import IntEnum, Enum
from dotenv import load_dotenv


def strtobool(value: Any) -> bool:
    """将字符串转换为布尔值"""
    if isinstance(value, bool):
        return value
    value = str(value).lower()
    if value in {'true', '1', 'yes', 'y', 't'}:
        return True
    elif value in {'false', '0', 'no', 'n', 'f'}:
        return False
    raise ValueError(f"无法解析的布尔值: {value}")


# 枚举定义
class EnvironmentType(Enum):
    """环境类型"""
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'


class SQLRiskLevel(IntEnum):
    """SQL操作风险等级"""
    LOW = 1  # 查询操作（SELECT）
    MEDIUM = 2  # 基本数据修改（INSERT，有WHERE的UPDATE/DELETE）
    HIGH = 3  # 结构变更（CREATE/ALTER）和无WHERE的数据修改
    CRITICAL = 4  # 危险操作（DROP/TRUNCATE等）


class DatabaseAccessLevel(Enum):
    """数据库访问级别"""
    STRICT = 'strict'
    RESTRICTED = 'restricted'
    PERMISSIVE = 'permissive'


def _get_env_type() -> EnvironmentType:
    """获取环境类型并转换"""
    env_str = os.getenv('ENV_TYPE', 'development').lower()
    try:
        return EnvironmentType(env_str)
    except ValueError:
        return EnvironmentType.DEVELOPMENT


def _get_blocked_patterns() -> List[str]:
    """获取阻止的SQL模式列表"""
    patterns_str = os.getenv('BLOCKED_PATTERNS', '')
    return [p.strip().upper() for p in patterns_str.split(',') if p.strip()]


class AppConfigManager:
    """应用配置的统一管理器"""

    # SQL操作集合
    DDL_OPERATIONS = {'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME'}
    DML_OPERATIONS = {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE'}
    METADATA_OPERATIONS = {'SHOW', 'DESC', 'DESCRIBE', 'EXPLAIN', 'HELP', 'ANALYZE', 'CHECK', 'CHECKSUM', 'OPTIMIZE'}

    # 角色权限
    ROLE_PERMISSIONS = {
        "readonly": ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN"],
        "admin": ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"]
    }

    def __init__(self):
        load_dotenv()  # 加载环境变量
        self._load_config()

    def _load_config(self) -> None:
        """加载所有配置项"""
        # 服务器配置
        self.HOST = os.getenv('HOST', '127.0.0.1')
        self.PORT = int(os.getenv('PORT', '3000'))
        self.ENV_TYPE = _get_env_type()
        self.MCP_LOGIN_URL = os.getenv('MCP_LOGIN_URL', 'http://localhost:3000/login')
        self.OAUTH_USER_NAME = os.getenv('OAUTH_USER_NAME', 'admin')
        self.OAUTH_USER_PASSWORD = os.getenv('OAUTH_USER_PASSWORD', 'admin')

        # 数据库配置
        self.MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
        self.MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
        self.MYSQL_USER = os.getenv('MYSQL_USER')
        self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD')
        self.MYSQL_DATABASE = os.getenv('MYSQL_DATABASE')
        self.MYSQL_ROLE = os.getenv('MYSQL_ROLE', 'readonly')
        self.DB_AUTH_PLUGIN = os.getenv('DB_AUTH_PLUGIN', 'mysql_native_password')
        self.DB_CONNECTION_TIMEOUT = int(os.getenv('DB_CONNECTION_TIMEOUT', '5'))

        # 连接池配置
        self.DB_POOL_ENABLED = strtobool(os.getenv('DB_POOL_ENABLED', 'false'))
        self.DB_POOL_MIN_SIZE = int(os.getenv('DB_POOL_MIN_SIZE', '5'))
        self.DB_POOL_MAX_SIZE = int(os.getenv('DB_POOL_MAX_SIZE', '20'))
        self.DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', '300'))
        self.DB_POOL_MAX_LIFETIME = int(os.getenv('DB_POOL_MAX_LIFETIME', '0'))
        self.DB_POOL_ACQUIRE_TIMEOUT = float(os.getenv('DB_POOL_ACQUIRE_TIMEOUT', '10.0'))

        # 安全配置
        self.ALLOWED_RISK_LEVELS = self._get_allowed_risk_levels()
        self.ALLOW_SENSITIVE_INFO = strtobool(os.getenv('ALLOW_SENSITIVE_INFO', 'false'))
        self.MAX_SQL_LENGTH = int(os.getenv('MAX_SQL_LENGTH', '1000'))
        self.BLOCKED_PATTERNS = _get_blocked_patterns()
        self.ENABLE_QUERY_CHECK = strtobool(os.getenv('ENABLE_QUERY_CHECK', 'true'))
        self.ENABLE_DATABASE_ISOLATION = self._get_db_isolation_setting()
        self.DATABASE_ACCESS_LEVEL = self._get_db_access_level()

        # 日志配置
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')

        # 验证必要配置
        if not all([self.MYSQL_USER, self.MYSQL_PASSWORD, self.MYSQL_DATABASE]):
            raise ValueError("缺少必要的数据库配置信息")

    def _get_allowed_risk_levels(self) -> Set[SQLRiskLevel]:
        """获取允许的风险等级"""
        allowed_levels: Set[SQLRiskLevel] = set()
        levels_str = os.getenv('ALLOWED_RISK_LEVELS', '')

        # 生产环境默认只允许低风险操作
        if self.ENV_TYPE == EnvironmentType.PRODUCTION and not levels_str:
            return {SQLRiskLevel.LOW}

        # 解析配置的风险等级
        for level_str in levels_str.upper().split(','):
            level_str = level_str.strip()
            try:
                # 明确添加枚举值
                level_value = getattr(SQLRiskLevel, level_str)
                allowed_levels.add(level_value)
            except AttributeError:
                continue  # 跳过无效的风险等级

        return allowed_levels

    def _get_db_isolation_setting(self) -> bool:
        """获取数据库隔离设置"""
        # 生产环境强制启用数据库隔离
        if self.ENV_TYPE == EnvironmentType.PRODUCTION:
            return True

        return strtobool(os.getenv('ENABLE_DATABASE_ISOLATION', 'false'))

    def _get_db_access_level(self) -> DatabaseAccessLevel:
        """获取数据库访问级别"""
        # 生产环境默认使用限制模式
        if self.ENV_TYPE == EnvironmentType.PRODUCTION and not os.getenv('DATABASE_ACCESS_LEVEL'):
            return DatabaseAccessLevel.RESTRICTED

        level_str = os.getenv('DATABASE_ACCESS_LEVEL', 'permissive').lower()
        try:
            return DatabaseAccessLevel(level_str)
        except ValueError:
            return DatabaseAccessLevel.PERMISSIVE

    def get_database_config(self) -> dict:
        """获取数据库连接配置"""
        return {
            'host': self.MYSQL_HOST,
            'port': self.MYSQL_PORT,
            'user': self.MYSQL_USER,
            'password': self.MYSQL_PASSWORD,
            'database': self.MYSQL_DATABASE,
            'role': self.MYSQL_ROLE,
            'auth_plugin': self.DB_AUTH_PLUGIN,
            'connection_timeout': self.DB_CONNECTION_TIMEOUT
        }

    def get_pool_config(self) -> dict:
        """获取连接池配置"""
        return {
            'enabled': self.DB_POOL_ENABLED,
            'min_size': self.DB_POOL_MIN_SIZE,
            'max_size': self.DB_POOL_MAX_SIZE,
            'recycle': self.DB_POOL_RECYCLE,
            'max_lifetime': self.DB_POOL_MAX_LIFETIME,
            'acquire_timeout': self.DB_POOL_ACQUIRE_TIMEOUT
        }

    def get_security_config(self) -> dict:
        """获取安全配置"""
        return {
            'env_type': self.ENV_TYPE,
            'allowed_risk_levels': self.ALLOWED_RISK_LEVELS,
            'allow_sensitive_info': self.ALLOW_SENSITIVE_INFO,
            'max_sql_length': self.MAX_SQL_LENGTH,
            'blocked_patterns': self.BLOCKED_PATTERNS,
            'enable_query_check': self.ENABLE_QUERY_CHECK,
            'enable_database_isolation': self.ENABLE_DATABASE_ISOLATION,
            'database_access_level': self.DATABASE_ACCESS_LEVEL,
            'log_level': self.LOG_LEVEL
        }

    def get_server_config(self) -> dict:
        """获取服务器配置"""
        return {
            'host': self.HOST,
            'port': self.PORT,
            'login_url': self.MCP_LOGIN_URL,
            'oauth_user': self.OAUTH_USER_NAME,
            'oauth_password': self.OAUTH_USER_PASSWORD
        }

    # 权限检查方法
    def get_role_permissions(self, role: str = None) -> list:
        """获取指定角色的权限列表"""
        target_role = role or self.MYSQL_ROLE
        return self.ROLE_PERMISSIONS.get(target_role, self.ROLE_PERMISSIONS["readonly"])

    def validate_operation(self, operation: str, role: str = None) -> bool:
        """验证操作是否在角色权限内"""
        return operation in self.get_role_permissions(role)

    def is_operation_allowed(self, risk_level: SQLRiskLevel) -> bool:
        """检查指定风险等级的操作是否被允许"""
        return risk_level in self.ALLOWED_RISK_LEVELS

    # 其他辅助方法
    def is_production(self) -> bool:
        """检查是否为生产环境"""
        return self.ENV_TYPE == EnvironmentType.PRODUCTION

    def should_block_sql(self, sql: str) -> bool:
        """检查SQL是否包含被阻止的模式"""
        if not self.BLOCKED_PATTERNS:
            return False

        sql_upper = sql.upper()
        return any(pattern in sql_upper for pattern in self.BLOCKED_PATTERNS)


class EnvFileManager:
    """环境文件管理封装"""

    @staticmethod
    def update(update: dict, env_path: str = ".env") -> None:
        """原子化更新.env文件 - 修复换行问题"""
        # 读取现有内容
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # 创建更新后的内容列表
        updated_keys = set()
        new_lines = []

        # 处理现有行
        for line in lines:
            stripped_line = line.strip()
            # 跳过空行和注释行
            if not stripped_line or stripped_line.startswith("#"):
                new_lines.append(line)
                continue

            # 找到键值对
            if "=" in line:
                key, remaining = line.split("=", 1)
                key = key.strip()

                # 处理键值对行
                if key in update:
                    # 处理注释
                    comment_part = ""
                    if "#" in remaining:
                        value_part, comment = remaining.split("#", 1)
                        comment_part = f" #{comment}"
                    else:
                        value_part = remaining

                    # 替换值并添加回新行
                    formatted_value = update[key]
                    if any(char in formatted_value for char in " #\"'") and not formatted_value.startswith(('"', "'")):
                        if '"' in formatted_value:
                            formatted_value = f"'{formatted_value}'"
                        else:
                            formatted_value = f'"{formatted_value}"'

                    new_line = f"{key}={formatted_value}{comment_part}"
                    # 确保添加换行符
                    new_lines.append(new_line + "\n")
                    updated_keys.add(key)
                else:
                    # 保留未修改的行，保持原始换行符
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # 添加新配置项，确保每个配置项独立成行
        for key, value in update.items():
            if key not in updated_keys:
                # 处理特殊字符
                if any(char in value for char in " #\"'"):
                    if '"' in value:
                        formatted_value = f"'{value}'"
                    else:
                        formatted_value = f'"{value}"'
                else:
                    formatted_value = value

                # 确保新行独立且包含换行符
                new_line = f"{key}={formatted_value}"
                new_lines.append("\n")  # 先添加换行符与之前的内容分隔
                new_lines.append(new_line + "\n")

        # 原子写入
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)


# 使用示例
if __name__ == "__main__":
    config = AppConfigManager()

    print("服务器配置:", config.get_server_config())
    print("\n数据库配置:", config.get_database_config())
    print("\n连接池配置:", config.get_pool_config())
    print("\n安全配置:", config.get_security_config())

    # 检查权限
    print("\n权限检查:")
    print("SELECT 操作允许:", config.validate_operation("SELECT"))
    print("DELETE 操作允许:", config.validate_operation("DELETE"))

    # 检查风险等级
    print("\n风险等级检查:")
    print("LOW 风险允许:", config.is_operation_allowed(SQLRiskLevel.LOW))
    print("CRITICAL 风险允许:", config.is_operation_allowed(SQLRiskLevel.CRITICAL))

    # 更新环境变量
    try:
        updates = {
            "MAX_SQL_LENGTH": "5000",
            "DB_POOL_MAX_SIZE": "30",
            "DB_POL_MAX_SIZE": "500"
        }

        EnvFileManager.update(updates)
        print("\n环境变量更新成功")

        # 重新加载配置查看更新效果
        config = AppConfigManager()
        print("\n更新后的安全配置:", config.get_security_config())
        print("更新后的连接池配置:", config.get_pool_config())

    except Exception as e:
        print(f"更新失败: {e}")
