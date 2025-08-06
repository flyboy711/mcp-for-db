import os
from typing import Dict, Any, List, Set
from pathlib import Path
from dotenv import load_dotenv
from enum import Enum, IntEnum


class EnvironmentType(Enum):
    """环境类型"""
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'


class SQLRiskLevel(IntEnum):
    """SQL操作风险等级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class DatabaseAccessLevel(Enum):
    """数据库访问级别"""
    STRICT = 'strict'
    RESTRICTED = 'restricted'
    PERMISSIVE = 'permissive'


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


class ConfigManager:
    """统一配置管理器"""

    def __init__(self, config_dir: str = os.path.join(Path(__file__).parent.parent.parent.parent, "envs"),
                 root_env_file: str = os.path.join(Path(__file__).parent.parent.parent.parent, ".env")):
        self.config_dir = config_dir  # 其他服务的配置目录
        self.root_env_file = root_env_file  # 环境配置根目录
        self.configs: Dict[str, Dict[str, Any]] = {}  # 不同服务的环境配置信息
        self.global_config: Dict[str, Any] = {}  # 全局配置: .env + common.env
        self._load_configs()

    def _load_configs(self):
        """加载所有配置文件"""
        # 首先加载全局配置（.env文件）
        # if os.path.exists(self.root_env_file):
        #     load_dotenv(self.root_env_file, override=True)

        # 加载通用配置（common.env）
        common_env = os.path.join(self.config_dir, "common.env")
        if os.path.exists(common_env):
            load_dotenv(common_env, override=True)

        # 保存全局配置（包含.env和common.env的内容）
        self.global_config = dict(os.environ)

        # 加载各服务的特定配置
        if os.path.exists(self.config_dir):
            for config_file in Path(self.config_dir).glob("*.env"):
                if config_file.name != "common.env":
                    service_name = config_file.stem

                    # 恢复环境变量到加载该服务配置前的状态
                    os.environ.clear()

                    # 加载服务特定配置
                    load_dotenv(config_file, override=True)

                    # 提取该服务的配置
                    self.configs[service_name] = self._load_service_config(service_name)

    def _load_service_config(self, service_name: str) -> Dict[str, Any]:
        """加载特定服务的配置"""
        config = {}

        # 先添加全局和通用配置
        common_keys = self._get_common_config_keys()
        for key in common_keys:
            config[key] = self.global_config[key]

        # 添加服务特定配置
        for key, value in os.environ.items():
            config[key] = value

        return config

    def _get_common_config_keys(self) -> Set[str]:
        """获取通用配置键名"""
        return {
            'HOST', 'PORT', 'ENV_TYPE', 'MCP_LOGIN_URL',
            'OAUTH_USER_NAME', 'OAUTH_USER_PASSWORD',
            'LOG_LEVEL', 'MAX_RETRY_COUNT'
        }

    def get_service_config(self, service_name: str) -> Dict[str, Any]:
        """获取服务配置"""
        return self.configs.get(service_name, {})

    def get_global_config(self, key: str, default: Any = None) -> Any:
        """获取全局配置"""
        return self.global_config.get(key, default)

    def get_config_value(self, service_name: str, key: str, default: Any = None) -> Any:
        """获取特定服务的配置值"""
        service_config = self.get_service_config(service_name)
        return service_config.get(key, default)

    def list_available_services(self) -> List[str]:
        """列出可用服务"""
        return list(self.configs.keys())

    def update_service_config(self, service_name: str, updates: Dict[str, Any]):
        """更新服务配置"""
        if service_name not in self.configs:
            self.configs[service_name] = {}
        self.configs[service_name].update(updates)

        # 同时更新环境变量
        for key, value in updates.items():
            if value is not None:
                env_key = f"{service_name.upper()}_{key.upper()}"
                os.environ[env_key] = str(value)

    def create_session_config_manager(self, service_name: str):
        """为特定服务创建会话配置管理器"""
        try:
            from mcp_for_db.server.server_mysql.config.session_config import SessionConfigManager
            config = self.get_service_config(service_name)
            return SessionConfigManager(config if config else None)
        except ImportError as e:
            return None


if __name__ == '__main__':
    config_manager = ConfigManager()

    print("可用的服务:", config_manager.list_available_services())
    print("MySQL 配置:")
    mysql_config = config_manager.get_service_config("mysql")
    for key, value in mysql_config.items():
        print(f"  {key} = {value}")

    print("DiFy 配置:")
    dify_config = config_manager.get_service_config("dify")
    for key, value in dify_config.items():
        print(f"  {key} = {value}")

    update_dict = {
        "MYSQL_PORT": "13309",
        "MYSQL_USER": "videx1",
    }

    config_manager.update_service_config("mysql", update_dict)
    print("MySQL 更新后的配置:")
    mysql_config = config_manager.get_service_config("mysql")
    for key, value in mysql_config.items():
        print(f"  {key} = {value}")
