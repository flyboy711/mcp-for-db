import os
import hashlib
from typing import List, Set, Dict, Any, Optional
from enum import Enum, IntEnum
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


def get_env_type() -> EnvironmentType:
    """获取环境类型并转换"""
    env_str = os.getenv('ENV_TYPE', 'development').lower()
    try:
        return EnvironmentType(env_str)
    except ValueError:
        return EnvironmentType.DEVELOPMENT


def get_blocked_patterns() -> List[str]:
    """获取阻止的SQL模式列表"""
    patterns_str = os.getenv('BLOCKED_PATTERNS', '')
    return [p.strip().upper() for p in patterns_str.split(',') if p.strip()]


def parse_risk_levels(levels_str: str) -> Set[SQLRiskLevel]:
    """解析风险等级字符串"""
    allowed_levels: Set[SQLRiskLevel] = set()
    if not levels_str:
        return allowed_levels

    for level_str in levels_str.upper().split(','):
        level_str = level_str.strip()
        try:
            # 尝试从SQLRiskLevel枚举中获取值
            level_value = getattr(SQLRiskLevel, level_str)
            allowed_levels.add(level_value)
        except AttributeError:
            continue  # 跳过无效的风险等级
    return allowed_levels


def _get_db_isolation_setting() -> bool:
    """获取数据库隔离设置"""
    # 生产环境强制启用数据库隔离
    if get_env_type() == EnvironmentType.PRODUCTION:
        return True
    return strtobool(os.getenv('ENABLE_DATABASE_ISOLATION', 'false'))


def _get_db_access_level() -> DatabaseAccessLevel:
    """获取数据库访问级别"""
    # 生产环境默认使用限制模式
    if get_env_type() == EnvironmentType.PRODUCTION and not os.getenv('DATABASE_ACCESS_LEVEL'):
        return DatabaseAccessLevel.RESTRICTED

    level_str = os.getenv('DATABASE_ACCESS_LEVEL', 'permissive').lower()
    try:
        return DatabaseAccessLevel(level_str)
    except ValueError:
        return DatabaseAccessLevel.PERMISSIVE


class SessionConfigManager:
    """会话级配置管理器，支持动态更新配置"""

    def __init__(self, initial_config: Optional[Dict[str, Any]] = None):
        self.config: Dict[str, Any] = {}
        self._config_hash = ''

        if initial_config is not None:
            # 进行类型转换
            self.config = self._normalize_external_config(initial_config).copy()
        else:
            self._load_from_env()

        self._update_hash()

    def _normalize_external_config(self, raw_config: Dict[str, Any]) -> Dict[str, Any]:
        """将外部传入的配置进行类型转换和标准化处理"""
        normalized = {}

        # 转换环境类型
        env_str = raw_config.get('ENV_TYPE', 'development').lower()
        normalized['ENV_TYPE'] = EnvironmentType(
            env_str if env_str in ('development', 'production') else 'development').value

        # 转换风险等级
        if 'ALLOWED_RISK_LEVELS' in raw_config:
            risk_str = str(raw_config['ALLOWED_RISK_LEVELS'])
            normalized['ALLOWED_RISK_LEVELS'] = self._parse_risk_levels(risk_str)
        else:
            # 如果没有提供，使用默认值
            normalized['ALLOWED_RISK_LEVELS'] = self._parse_risk_levels("LOW")

        # 处理阻止模式
        if 'BLOCKED_PATTERNS' in raw_config:
            patterns = raw_config['BLOCKED_PATTERNS']
            if isinstance(patterns, str):
                self.config['BLOCKED_PATTERNS'] = [
                    p.strip().upper() for p in patterns.split(',') if p.strip()
                ]
            elif isinstance(patterns, list):
                self.config['BLOCKED_PATTERNS'] = [
                    str(p).strip().upper() for p in patterns
                ]
            else:
                self.config['BLOCKED_PATTERNS'] = ['DROP TABLE,DROP DATABASE,DELETE FROM']
        else:
            self.config['BLOCKED_PATTERNS'] = ['DROP TABLE,DROP DATABASE,DELETE FROM']

        # 转换数据库访问级别
        if 'DATABASE_ACCESS_LEVEL' in raw_config:
            level_str = str(raw_config['DATABASE_ACCESS_LEVEL']).lower()
            try:
                normalized['DATABASE_ACCESS_LEVEL'] = DatabaseAccessLevel(level_str).value
            except ValueError:
                # 如果传入值无效，使用默认
                normalized['DATABASE_ACCESS_LEVEL'] = DatabaseAccessLevel.PERMISSIVE.value

        # 处理布尔值转换
        for bool_key in [
            'DB_POOL_ENABLED',
            'ALLOW_SENSITIVE_INFO',
            'ENABLE_QUERY_CHECK',
            'ENABLE_DATABASE_ISOLATION'
        ]:
            if bool_key in raw_config:
                normalized[bool_key] = strtobool(raw_config[bool_key])

        # 处理数值类型
        for int_key in [
            'MYSQL_PORT', 'DB_CONNECTION_TIMEOUT',
            'DB_POOL_MIN_SIZE', 'DB_POOL_MAX_SIZE',
            'DB_POOL_RECYCLE', 'DB_POOL_MAX_LIFETIME',
            'MAX_SQL_LENGTH'
        ]:
            if int_key in raw_config:
                try:
                    normalized[int_key] = int(raw_config[int_key])
                except (TypeError, ValueError):
                    # 缺失就没配置
                    pass

        # 处理浮点数
        if 'DB_POOL_ACQUIRE_TIMEOUT' in raw_config:
            try:
                normalized['DB_POOL_ACQUIRE_TIMEOUT'] = float(raw_config['DB_POOL_ACQUIRE_TIMEOUT'])
            except (TypeError, ValueError):
                pass

        # 直接复制其余不需要特殊处理的配置项
        for key in raw_config:
            if key not in normalized:
                normalized[key] = raw_config[key]

        # 确保生产环境的强制规则
        if normalized.get('ENV_TYPE') == 'production':
            normalized['ENABLE_DATABASE_ISOLATION'] = True
            if 'DATABASE_ACCESS_LEVEL' not in normalized:
                normalized['DATABASE_ACCESS_LEVEL'] = DatabaseAccessLevel.RESTRICTED.value

        return normalized

    def _update_hash(self) -> None:
        self._config_hash = hashlib.md5(str(self.config).encode('utf-8')).hexdigest()

    def _parse_int_env(self, key: str, default: int) -> int:
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _parse_float_env(self, key: str, default: float) -> float:
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _parse_bool_env(self, key: str, default: bool) -> bool:
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return strtobool(value)
        except ValueError:
            return default

    def _parse_risk_levels(self, levels_str: str) -> Set[SQLRiskLevel]:
        """解析风险等级字符串为 SQLRiskLevel 枚举集合"""
        allowed_levels: Set[SQLRiskLevel] = set()
        if not levels_str:
            return allowed_levels

        # 确保 levels_str 是字符串
        levels_str = str(levels_str).upper()

        for level_str in levels_str.split(','):
            level_str = level_str.strip()
            if not level_str:
                continue

            # 尝试按名称匹配
            try:
                level_value = SQLRiskLevel[level_str]
                allowed_levels.add(level_value)
                continue
            except KeyError:
                pass

            # 尝试按值匹配
            try:
                level_value = int(level_str)
                if level_value in {item.value for item in SQLRiskLevel}:
                    allowed_levels.add(SQLRiskLevel(level_value))
                    continue
            except (ValueError, TypeError):
                pass

        return allowed_levels

    def _load_from_env(self, env_path: str = ".env") -> None:
        load_dotenv(env_path, override=True)
        # 服务器配置
        self.config['HOST'] = os.getenv('HOST', '127.0.0.1')
        self.config['PORT'] = self._parse_int_env('PORT', 3000)
        self.config['ENV_TYPE'] = get_env_type().value
        self.config['MCP_LOGIN_URL'] = os.getenv('MCP_LOGIN_URL', 'http://localhost:3000/login')
        self.config['OAUTH_USER_NAME'] = os.getenv('OAUTH_USER_NAME')
        self.config['OAUTH_USER_PASSWORD'] = os.getenv('OAUTH_USER_PASSWORD')

        # 数据库配置
        self.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
        self.config['MYSQL_PORT'] = self._parse_int_env('MYSQL_PORT', 3306)
        self.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
        self.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
        self.config['MYSQL_DATABASE'] = os.getenv('MYSQL_DATABASE')
        self.config['DB_AUTH_PLUGIN'] = os.getenv('DB_AUTH_PLUGIN', 'mysql_native_password')
        self.config['DB_CONNECTION_TIMEOUT'] = self._parse_int_env('DB_CONNECTION_TIMEOUT', 5)

        # 连接池配置
        self.config['DB_POOL_ENABLED'] = self._parse_bool_env('DB_POOL_ENABLED', False)
        self.config['DB_POOL_MIN_SIZE'] = self._parse_int_env('DB_POOL_MIN_SIZE', 5)
        self.config['DB_POOL_MAX_SIZE'] = self._parse_int_env('DB_POOL_MAX_SIZE', 20)
        self.config['DB_POOL_RECYCLE'] = self._parse_int_env('DB_POOL_RECYCLE', 300)
        self.config['DB_POOL_MAX_LIFETIME'] = self._parse_int_env('DB_POOL_MAX_LIFETIME', 0)
        self.config['DB_POOL_ACQUIRE_TIMEOUT'] = self._parse_float_env('DB_POOL_ACQUIRE_TIMEOUT', 10.0)

        # 安全配置
        # 处理风险等级
        risk_str = os.getenv('ALLOWED_RISK_LEVELS', 'LOW')
        self.config['ALLOWED_RISK_LEVELS'] = self._parse_risk_levels(risk_str)

        self.config['ALLOW_SENSITIVE_INFO'] = self._parse_bool_env('ALLOW_SENSITIVE_INFO', False)
        self.config['MAX_SQL_LENGTH'] = self._parse_int_env('MAX_SQL_LENGTH', 1000)

        # 处理阻止模式
        blocked_str = os.getenv('BLOCKED_PATTERNS', 'DROP TABLE,DROP DATABASE,DELETE FROM')
        self.config['BLOCKED_PATTERNS'] = [
            p.strip().upper() for p in blocked_str.split(',') if p.strip()
        ]

        self.config['ENABLE_QUERY_CHECK'] = self._parse_bool_env('ENABLE_QUERY_CHECK', True)
        self.config['ENABLE_DATABASE_ISOLATION'] = _get_db_isolation_setting()
        self.config['DATABASE_ACCESS_LEVEL'] = _get_db_access_level().value

    def update(self, new_cfg: Dict[str, Any]) -> None:
        self.config.update(new_cfg)
        self._update_hash()

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        return self.config.copy()

    def _compute_config_hash(self) -> str:
        return hashlib.md5(str(self.config).encode('utf-8')).hexdigest()


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


# 示例使用
if __name__ == "__main__":
    # 创建默认会话配置
    session_config = SessionConfigManager()

    # 使用新的get方法获取配置值
    print("数据库配置:")
    print(f"MySQL主机: {session_config.get('MYSQL_HOST')}")
    print(f"MySQL端口: {session_config.get('MYSQL_PORT')}")
    print(f"MySQL用户: {session_config.get('MYSQL_USER')}")
    print(f"MySQL密码: {session_config.get('MYSQL_PASSWORD')}")
    print(f"MySQL数据库: {session_config.get('MYSQL_DATABASE')}")
    print(f"连接超时: {session_config.get('DB_CONNECTION_TIMEOUT')}秒")
    print(f"认证插件: {session_config.get('DB_AUTH_PLUGIN')}")

    print("\n连接池配置:")
    print(f"连接池启用: {session_config.get('DB_POOL_ENABLED')}")
    print(f"最小连接数: {session_config.get('DB_POOL_MIN_SIZE')}")
    print(f"最大连接数: {session_config.get('DB_POOL_MAX_SIZE')}")
    print(f"连接回收时间: {session_config.get('DB_POOL_RECYCLE')}秒")
    print(f"连接最大存活时间: {session_config.get('DB_POOL_MAX_LIFETIME')}秒")
    print(f"获取连接超时: {session_config.get('DB_POOL_ACQUIRE_TIMEOUT')}秒")

    print("\n安全配置:")
    print(f"允许的风险等级: {session_config.get('ALLOWED_RISK_LEVELS')}")
    print(f"允许敏感信息: {session_config.get('ALLOW_SENSITIVE_INFO')}")
    print(f"最大SQL长度: {session_config.get('MAX_SQL_LENGTH')}")
    print(f"阻止的模式: {session_config.get('BLOCKED_PATTERNS')}")
    print(f"启用查询检查: {session_config.get('ENABLE_QUERY_CHECK')}")
    print(f"启用数据库隔离: {session_config.get('ENABLE_DATABASE_ISOLATION')}")
    print(f"数据库访问级别: {session_config.get('DATABASE_ACCESS_LEVEL')}")

    print("\n服务器配置:")
    print(f"主机: {session_config.get('HOST')}")
    print(f"端口: {session_config.get('PORT')}")
    print(f"环境类型: {session_config.get('ENV_TYPE')}")
    print(f"登录URL: {session_config.get('MCP_LOGIN_URL')}")
    print(f"OAuth用户名: {session_config.get('OAUTH_USER_NAME')}")
    print(f"OAuth密码: {session_config.get('OAUTH_USER_PASSWORD')}")

    # 更新会话配置
    new_config = {
        "MYSQL_PORT": "3306"
    }
    session_config.update(new_config)
    print("\n更新后的配置:")
    print(f"MySQL端口: {session_config.get('MYSQL_PORT')}")

    updates = {
        "MYSQL_PORT": "13309",
        "MYSQL_USER": "videx1",
    }

    # 获取当前文件所在目录的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(current_dir, ".env")

    EnvFileManager.update(updates, env_file)
    print("\n环境变量更新成功")

    session_config1 = SessionConfigManager()
    print(f"MySQL端口: {session_config1.get('MYSQL_PORT')}")
