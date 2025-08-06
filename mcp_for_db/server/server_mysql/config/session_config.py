import os
import hashlib
from pathlib import Path
from typing import Set, Dict, Any, Optional, List, Callable
from dataclasses import dataclass
from dotenv import load_dotenv
from mcp_for_db.server.core import EnvironmentType, SQLRiskLevel, DatabaseAccessLevel, strtobool


@dataclass
class ConfigSchema:
    """配置模式定义"""
    key: str
    default: Any
    type_converter: Callable[[Any], Any]
    validator: Optional[Callable[[Any], bool]] = None
    description: str = ""


class ConfigNormalizer:
    """配置标准化处理器"""

    # 配置类型映射
    TYPE_CONVERTERS = {
        'bool': lambda x: strtobool(str(x)) if not isinstance(x, bool) else x,
        'int': lambda x: int(float(str(x).strip())) if not isinstance(x, int) else x,
        'float': lambda x: float(str(x).strip()) if not isinstance(x, (int, float)) else float(x),
        'str': lambda x: str(x).strip().strip('\'"') if isinstance(x, str) else str(x),
        'list': lambda x: x if isinstance(x, list) else [s.strip() for s in str(x).split(',') if s.strip()],
        'risk_levels': lambda x: ConfigNormalizer._parse_risk_levels(str(x)),
        'access_level': lambda x: ConfigNormalizer._parse_access_level(x),
        'env_type': lambda x: ConfigNormalizer._parse_env_type(x),
        'blocked_patterns': lambda x: ConfigNormalizer._parse_blocked_patterns(x)
    }

    @staticmethod
    def _parse_risk_levels(levels_str: str) -> Set[SQLRiskLevel]:
        """解析风险等级字符串"""
        if not levels_str:
            return {SQLRiskLevel.LOW}

        allowed_levels = set()
        for level_str in levels_str.upper().split(','):
            level_str = level_str.strip()
            try:
                # 确保返回SQLRiskLevel枚举对象，而不是字符串
                if hasattr(SQLRiskLevel, level_str):
                    allowed_levels.add(getattr(SQLRiskLevel, level_str))
            except AttributeError:
                continue
        return allowed_levels or {SQLRiskLevel.LOW}

    @staticmethod
    def _parse_access_level(value: Any) -> str:
        """解析数据库访问级别"""
        try:
            return DatabaseAccessLevel(str(value).lower().strip()).value
        except (ValueError, AttributeError):
            return DatabaseAccessLevel.PERMISSIVE.value

    @staticmethod
    def _parse_env_type(value: Any) -> str:
        """解析环境类型"""
        try:
            env_str = str(value).lower().strip()
            if env_str in ('development', 'production', 'testing', 'staging'):
                return EnvironmentType(env_str).value
            return EnvironmentType.DEVELOPMENT.value
        except (ValueError, AttributeError):
            return EnvironmentType.DEVELOPMENT.value

    @staticmethod
    def _parse_blocked_patterns(value: Any) -> List[str]:
        """解析阻止模式"""
        if isinstance(value, str):
            value = value.strip('\'"')
            if not value:
                return ConfigNormalizer._get_default_blocked_patterns()
            return [p.strip().upper() for p in value.split(',') if p.strip()]
        elif isinstance(value, list):
            patterns = [str(p).strip().upper() for p in value if str(p).strip()]
            return patterns if patterns else ConfigNormalizer._get_default_blocked_patterns()
        return ConfigNormalizer._get_default_blocked_patterns()

    @staticmethod
    def _get_default_blocked_patterns() -> List[str]:
        return ['DROP TABLE', 'DROP DATABASE', 'DELETE FROM', 'TRUNCATE TABLE', 'ALTER TABLE', 'CREATE TABLE',
                'DROP INDEX']

    @classmethod
    def normalize(cls, key: str, value: Any, type_name: str) -> Any:
        """通用标准化方法"""
        if value is None:
            return None

        converter = cls.TYPE_CONVERTERS.get(type_name, cls.TYPE_CONVERTERS['str'])
        try:
            return converter(value)
        except (ValueError, TypeError) as e:
            # 记录错误但不阻断处理
            return value


class ConfigSchemaRegistry:
    """配置模式注册表"""

    # 全局配置模式
    GLOBAL_SCHEMAS = [
        ConfigSchema('ENV_TYPE', 'development', 'env_type', description="环境类型"),
        ConfigSchema('HOST', '127.0.0.1', 'str', description="服务器主机"),
        ConfigSchema('PORT', 3000, 'int', description="服务器端口"),
        ConfigSchema('MCP_LOGIN_URL', 'http://localhost:3000/login', 'str', description="登录URL"),
        ConfigSchema('OAUTH_USER_NAME', '', 'str', description="OAuth用户名"),
        ConfigSchema('OAUTH_USER_PASSWORD', '', 'str', description="OAuth密码"),
    ]

    # MySQL配置模式
    MYSQL_SCHEMAS = [
        # 连接配置
        ConfigSchema('MYSQL_HOST', 'localhost', 'str', description="MySQL主机"),
        ConfigSchema('MYSQL_PORT', 3306, 'int', description="MySQL端口"),
        ConfigSchema('MYSQL_USER', '', 'str', description="MySQL用户名"),
        ConfigSchema('MYSQL_PASSWORD', '', 'str', description="MySQL密码"),
        ConfigSchema('MYSQL_DATABASE', '', 'str', description="MySQL数据库名"),
        ConfigSchema('MYSQL_DB_AUTH_PLUGIN', 'mysql_native_password', 'str', description="认证插件"),
        ConfigSchema('MYSQL_DB_CONNECTION_TIMEOUT', 5, 'int', description="连接超时"),

        # 连接池配置
        ConfigSchema('MYSQL_DB_POOL_ENABLED', False, 'bool', description="启用连接池"),
        ConfigSchema('MYSQL_DB_POOL_MIN_SIZE', 5, 'int', description="连接池最小大小"),
        ConfigSchema('MYSQL_DB_POOL_MAX_SIZE', 20, 'int', description="连接池最大大小"),
        ConfigSchema('MYSQL_DB_POOL_RECYCLE', 300, 'int', description="连接回收时间"),
        ConfigSchema('MYSQL_DB_POOL_MAX_LIFETIME', 0, 'int', description="连接最大生存时间"),
        ConfigSchema('MYSQL_DB_POOL_ACQUIRE_TIMEOUT', 10.0, 'float', description="获取连接超时"),

        # 安全配置
        ConfigSchema('MYSQL_ALLOWED_RISK_LEVELS', 'LOW', 'risk_levels', description="允许的风险等级"),
        ConfigSchema('MYSQL_ENABLE_QUERY_CHECK', True, 'bool', description="启用查询检查"),
        ConfigSchema('MYSQL_MAX_SQL_LENGTH', 2000, 'int', description="最大SQL长度"),
        ConfigSchema('MYSQL_BLOCKED_PATTERNS', 'DROP TABLE,DROP DATABASE,TRUNCATE', 'blocked_patterns',
                     description="阻止模式"),
        ConfigSchema('MYSQL_ENABLE_DATABASE_ISOLATION', False, 'bool', description="启用数据库隔离"),
        ConfigSchema('MYSQL_DATABASE_ACCESS_LEVEL', 'permissive', 'access_level', description="数据库访问级别"),
    ]

    @classmethod
    def get_all_schemas(cls) -> Dict[str, ConfigSchema]:
        """获取所有配置模式"""
        schemas = {}
        for schema in cls.GLOBAL_SCHEMAS + cls.MYSQL_SCHEMAS:
            schemas[schema.key] = schema
        return schemas


class EnvironmentLoader:
    """环境文件加载器"""

    def __init__(self, service_name: str = "mysql"):
        self.service_name = service_name
        self.root_dir = Path(__file__).parent.parent.parent.parent.parent

    def load_env_files(self) -> None:
        """加载环境文件"""
        # 加载通用配置
        common_env_path = self.root_dir / "envs" / "common.env"
        if common_env_path.exists():
            load_dotenv(common_env_path, override=False)

        # 加载服务特定配置
        service_env_path = self.root_dir / "envs" / f"{self.service_name}.env"
        if service_env_path.exists():
            load_dotenv(service_env_path, override=True)

    def load_config_from_env(self) -> Dict[str, Any]:
        """从环境变量加载配置"""
        self.load_env_files()

        config = {}
        schemas = ConfigSchemaRegistry.get_all_schemas()

        for key, schema in schemas.items():
            env_value = os.getenv(key)
            if env_value is not None:
                config[key] = ConfigNormalizer.normalize(key, env_value, schema.type_converter)
            else:
                config[key] = schema.default

        return config


class EnvironmentRuleEngine:
    """环境规则引擎"""

    @staticmethod
    def apply_environment_rules(config: Dict[str, Any], env_type: EnvironmentType) -> None:
        """应用环境特定规则"""
        if env_type == EnvironmentType.PRODUCTION:
            # 生产环境强制规则
            config.update({
                'MYSQL_ENABLE_DATABASE_ISOLATION': True,
                'MYSQL_ENABLE_QUERY_CHECK': True,
            })

            # 生产环境默认受限访问
            if 'MYSQL_DATABASE_ACCESS_LEVEL' not in config:
                config['MYSQL_DATABASE_ACCESS_LEVEL'] = DatabaseAccessLevel.RESTRICTED.value

            # 移除HIGH风险等级
            risk_levels = config.get('MYSQL_ALLOWED_RISK_LEVELS', set())
            if isinstance(risk_levels, set) and SQLRiskLevel.HIGH in risk_levels:
                config['MYSQL_ALLOWED_RISK_LEVELS'] = {r for r in risk_levels if r != SQLRiskLevel.HIGH}

        elif env_type == EnvironmentType.DEVELOPMENT:
            # 开发环境宽松规则
            if 'MYSQL_DATABASE_ACCESS_LEVEL' not in config:
                config['MYSQL_DATABASE_ACCESS_LEVEL'] = DatabaseAccessLevel.PERMISSIVE.value


class SessionConfigManager:
    """会话级配置管理器"""

    def __init__(self, initial_config: Optional[Dict[str, Any]] = None, service_name: str = "mysql"):
        self.service_name = service_name
        self.config: Dict[str, Any] = {}
        self._config_hash = ''
        self._global_env_type: Optional[EnvironmentType] = None

        # 加载配置
        if initial_config is not None:
            self.config = self._normalize_external_config(initial_config)
        else:
            self._load_from_env()

        self._update_hash()

    def _get_global_env_type(self) -> EnvironmentType:
        """获取全局环境类型"""
        if self._global_env_type is None:
            env_str = os.getenv('ENV_TYPE', 'development').lower()
            try:
                self._global_env_type = EnvironmentType(env_str)
            except ValueError:
                self._global_env_type = EnvironmentType.DEVELOPMENT
        return self._global_env_type

    def _normalize_external_config(self, raw_config: Dict[str, Any]) -> Dict[str, Any]:
        """标准化外部配置"""
        normalized = {}
        schemas = ConfigSchemaRegistry.get_all_schemas()

        # 标准化输入的配置
        for key, value in raw_config.items():
            key_upper = key.upper()
            schema = schemas.get(key_upper)

            if schema:
                normalized[key_upper] = ConfigNormalizer.normalize(key_upper, value, schema.type_converter)
            else:
                # 未知配置项直接存储
                normalized[key_upper] = value

        # 应用默认值
        self._apply_defaults(normalized, schemas)

        # 应用环境规则
        env_type = self._get_global_env_type()
        EnvironmentRuleEngine.apply_environment_rules(normalized, env_type)

        return normalized

    def _apply_defaults(self, config: Dict[str, Any], schemas: Dict[str, ConfigSchema]) -> None:
        """应用默认值"""
        for key, schema in schemas.items():
            if key not in config:
                config[key] = schema.default

    def _load_from_env(self) -> None:
        """从环境文件加载配置"""
        loader = EnvironmentLoader(self.service_name)
        self.config = loader.load_config_from_env()

        # 应用环境规则
        env_type = self._get_global_env_type()
        EnvironmentRuleEngine.apply_environment_rules(self.config, env_type)

    def _update_hash(self) -> None:
        """更新配置哈希"""
        self._config_hash = hashlib.md5(str(sorted(self.config.items())).encode('utf-8')).hexdigest()

    def get_global_env_type(self) -> EnvironmentType:
        """获取全局环境类型"""
        return self._get_global_env_type()

    def get_mysql_config(self) -> Dict[str, Any]:
        """获取MySQL相关配置"""
        return {k: v for k, v in self.config.items() if k.startswith('MYSQL_')}

    def update(self, new_cfg: Dict[str, Any]) -> None:
        """更新配置"""
        normalized_cfg = self._normalize_external_config(new_cfg)
        self.config.update(normalized_cfg)
        if 'ENV_TYPE' in normalized_cfg:
            self._global_env_type = None
        self._update_hash()

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self.config.copy()

    def get_config_hash(self) -> str:
        """获取配置哈希值"""
        return self._config_hash


class EnvFileManager:
    """环境文件管理器 - 简化版本"""

    @staticmethod
    def update_config_file(updates: Dict[str, Any], env_path: str) -> None:
        """通用的配置文件更新方法"""
        # 确保目录存在
        Path(env_path).parent.mkdir(parents=True, exist_ok=True)

        # 读取现有内容
        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        # 更新或添加配置
        updated_keys = set()
        new_lines = []

        # 处理现有行
        for line in lines:
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#"):
                new_lines.append(line)
                continue

            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in updates:
                    # 保留注释
                    comment = ""
                    if "#" in line:
                        comment = " " + line.split("#", 1)[1].rstrip() if "#" in line.split("=", 1)[1] else ""

                    formatted_value = EnvFileManager._format_value(updates[key])
                    new_lines.append(f"{key}={formatted_value}{comment}\n")
                    updated_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # 添加新的配置项
        for key, value in updates.items():
            if key not in updated_keys:
                formatted_value = EnvFileManager._format_value(value)
                new_lines.append(f"{key}={formatted_value}\n")

        # 写入文件
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    @staticmethod
    def update_mysql_config(updates: Dict[str, Any], env_path: str = None) -> None:
        """更新MySQL配置"""
        if env_path is None:
            root_dir = Path(__file__).parent.parent.parent.parent.parent
            env_path = root_dir / "envs" / "mysql.env"
        EnvFileManager.update_config_file(updates, str(env_path))

    @staticmethod
    def update_global_config(updates: Dict[str, Any], env_path: str = None) -> None:
        """更新全局配置"""
        if env_path is None:
            root_dir = Path(__file__).parent.parent.parent.parent.parent
            env_path = root_dir / "envs" / "common.env"
        EnvFileManager.update_config_file(updates, str(env_path))

    @staticmethod
    def _format_value(value: Any) -> str:
        """格式化配置值"""
        if isinstance(value, list):
            formatted_value = ','.join(str(v) for v in value)
        else:
            formatted_value = str(value)

        # 如果值包含特殊字符，添加引号
        if any(char in formatted_value for char in " #,\"'") and not formatted_value.startswith(('"', "'")):
            if '"' in formatted_value:
                formatted_value = f"'{formatted_value}'"
            else:
                formatted_value = f'"{formatted_value}"'

        return formatted_value


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
    print(f"连接超时: {session_config.get('MYSQL_DB_CONNECTION_TIMEOUT')}秒")
    print(f"认证插件: {session_config.get('MYSQL_DB_AUTH_PLUGIN')}")

    print("\n连接池配置:")
    print(f"连接池启用: {session_config.get('MYSQL_DB_POOL_ENABLED')}")
    print(f"最小连接数: {session_config.get('MYSQL_DB_POOL_MIN_SIZE')}")
    print(f"最大连接数: {session_config.get('MYSQL_DB_POOL_MAX_SIZE')}")
    print(f"连接回收时间: {session_config.get('MYSQL_DB_POOL_RECYCLE')}秒")
    print(f"连接最大存活时间: {session_config.get('MYSQL_DB_POOL_MAX_LIFETIME')}秒")
    print(f"获取连接超时: {session_config.get('MYSQL_DB_POOL_ACQUIRE_TIMEOUT')}秒")

    print("\n安全配置:")
    print(f"允许的风险等级: {session_config.get('MYSQL_ALLOWED_RISK_LEVELS')}")
    print(f"允许敏感信息: {session_config.get('MYSQL_ALLOW_SENSITIVE_INFO')}")
    print(f"最大SQL长度: {session_config.get('MYSQL_MAX_SQL_LENGTH')}")
    print(f"阻止的模式: {session_config.get('MYSQL_BLOCKED_PATTERNS')}")
    print(f"启用查询检查: {session_config.get('MYSQL_ENABLE_QUERY_CHECK')}")
    print(f"启用数据库隔离: {session_config.get('MYSQL_ENABLE_DATABASE_ISOLATION')}")
    print(f"数据库访问级别: {session_config.get('MYSQL_DATABASE_ACCESS_LEVEL')}")

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
    root_dir = Path(__file__).parent.parent.parent.parent.parent
    env_file = os.path.join(root_dir, "envs", "mysql.env")

    EnvFileManager.update_mysql_config(updates, env_file)
    print("\n环境变量更新成功\n")

    session_config1 = SessionConfigManager()
    print(f"MySQL端口: {session_config1.get('MYSQL_PORT')} \n\n")

    session_config_2 = SessionConfigManager({
        # 基础连接配置
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny",
        "MYSQL_DB_AUTH_PLUGIN": "mysql_native_password",
        "MYSQL_DB_CONNECTION_TIMEOUT": "10",

        # 连接池配置
        "MYSQL_DB_POOL_ENABLED": "true",
        "MYSQL_DB_POOL_MIN_SIZE": "3",
        "MYSQL_DB_POOL_MAX_SIZE": "15",
        "MYSQL_DB_POOL_RECYCLE": "600",
        "MYSQL_DB_POOL_MAX_LIFETIME": "3600",
        "MYSQL_DB_POOL_ACQUIRE_TIMEOUT": "15.0",

        # 安全配置
        "MYSQL_ALLOWED_RISK_LEVELS": "LOW,MEDIUM",
        "MYSQL_BLOCKED_PATTERNS": "DROP TABLE,TRUNCATE TABLE,DELETE FROM",
        "MYSQL_DATABASE_ACCESS_LEVEL": "restricted",
        "MYSQL_MAX_SQL_LENGTH": "5000",
        "MYSQL_ENABLE_QUERY_CHECK": "true",
        "MYSQL_ENABLE_DATABASE_ISOLATION": "true",

        # 全局配置（如果需要覆盖默认值）
        "ENV_TYPE": "production",
        "HOST": "0.0.0.0",
        "PORT": "8080",
        "MCP_LOGIN_URL": "https://example.com/login",
        "OAUTH_USER_NAME": "test_user",
        "OAUTH_USER_PASSWORD": "test_password",
    })

    # 完整的配置输出测试
    print("=== 基础连接配置 ===")
    print(f"MySQL主机: {session_config_2.get('MYSQL_HOST')}")
    print(f"MySQL端口: {session_config_2.get('MYSQL_PORT')}")
    print(f"MySQL用户: {session_config_2.get('MYSQL_USER')}")
    print(f"MySQL密码: {session_config_2.get('MYSQL_PASSWORD')}")
    print(f"MySQL数据库: {session_config_2.get('MYSQL_DATABASE')}")
    print(f"认证插件: {session_config_2.get('MYSQL_DB_AUTH_PLUGIN')}")
    print(f"连接超时: {session_config_2.get('MYSQL_DB_CONNECTION_TIMEOUT')}秒")

    print("\n=== 连接池配置 ===")
    print(f"连接池启用: {session_config_2.get('MYSQL_DB_POOL_ENABLED')}")
    print(f"连接池最小大小: {session_config_2.get('MYSQL_DB_POOL_MIN_SIZE')}")
    print(f"连接池最大大小: {session_config_2.get('MYSQL_DB_POOL_MAX_SIZE')}")
    print(f"连接回收时间: {session_config_2.get('MYSQL_DB_POOL_RECYCLE')}秒")
    print(f"连接最大生存时间: {session_config_2.get('MYSQL_DB_POOL_MAX_LIFETIME')}秒")
    print(f"获取连接超时: {session_config_2.get('MYSQL_DB_POOL_ACQUIRE_TIMEOUT')}秒")

    print("\n=== 安全配置 ===")
    print(f"允许的风险等级: {session_config_2.get('MYSQL_ALLOWED_RISK_LEVELS')}")
    print(f"最大SQL长度: {session_config_2.get('MYSQL_MAX_SQL_LENGTH')}")
    print(f"阻止的模式: {session_config_2.get('MYSQL_BLOCKED_PATTERNS')}")
    print(f"数据库访问级别: {session_config_2.get('MYSQL_DATABASE_ACCESS_LEVEL')}")
    print(f"启用查询检查: {session_config_2.get('MYSQL_ENABLE_QUERY_CHECK')}")
    print(f"启用数据库隔离: {session_config_2.get('MYSQL_ENABLE_DATABASE_ISOLATION')}")

    print("\n=== 全局配置 ===")
    print(f"环境类型: {session_config_2.get('ENV_TYPE')}")
    print(f"服务器主机: {session_config_2.get('HOST')}")
    print(f"服务器端口: {session_config_2.get('PORT')}")
    print(f"登录URL: {session_config_2.get('MCP_LOGIN_URL')}")
    print(f"OAuth用户名: {session_config_2.get('OAUTH_USER_NAME')}")
    print(f"OAuth密码: {session_config_2.get('OAUTH_USER_PASSWORD')}")

    # 测试MySQL特定配置获取
    print("\n=== MySQL专用配置 ===")
    mysql_config = session_config_2.get_mysql_config()
    for key, value in mysql_config.items():
        print(f"{key}: {value}")

    # 测试环境类型获取
    print(f"\n=== 环境信息 ===")
    print(f"全局环境类型: {session_config_2.get_global_env_type()}")
    print(f"配置哈希: {session_config_2.get_config_hash()}")

    # 测试配置更新
    print(f"\n=== 配置更新测试 ===")
    print(f"更新前MySQL端口: {session_config_2.get('MYSQL_PORT')}")

    session_config_2.update({
        "MYSQL_PORT": "13307",
        "MYSQL_MAX_SQL_LENGTH": "2000"
    })

    print(f"更新后MySQL端口: {session_config_2.get('MYSQL_PORT')}")
    print(f"更新后最大SQL长度: {session_config_2.get('MYSQL_MAX_SQL_LENGTH')}")
    print(f"更新后配置哈希: {session_config_2.get_config_hash()}")
