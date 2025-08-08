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


def strtobool(v: Any) -> bool:
    """将字符串转换为布尔值"""
    if isinstance(v, bool):
        return v
    v = str(v).lower()
    if v in {'true', '1', 'yes', 'y', 't'}:
        return True
    elif v in {'false', '0', 'no', 'n', 'f'}:
        return False
    raise ValueError(f"无法解析的布尔值: {v}")


class ConfigManager:
    """统一配置管理器: 注意采用 stdio 方式时读取配置文件的环境变量可能有问题

    环境变量的持久化修改也在这里维护
    """

    def __init__(self, config_dir: str = os.path.join(Path(__file__).parent.parent.parent, "envs")):
        self.config_dir = config_dir  # 其他服务的配置目录
        self.configs: Dict[str, Dict[str, Any]] = {}  # 不同服务的环境配置信息
        self.global_config: Dict[str, Any] = {}  # 全局配置: common.env
        self._load_configs()

    def _load_configs(self):
        """加载所有配置文件"""
        # 加载通用配置（common.env）
        common_env = os.path.join(self.config_dir, "common.env")
        if os.path.exists(common_env):
            load_dotenv(common_env, override=True)

        # 保存全局配置（仅包含 common.env 的内容）
        self.global_config = dict(os.environ)

        # 加载各服务的特定配置
        if os.path.exists(self.config_dir):
            for config_file in Path(self.config_dir).glob("*.env"):
                if config_file.name != "common.env":
                    service_name = config_file.stem

                    # 加载特定服务配置时清空环境变量
                    os.environ.clear()
                    # 加载服务特定配置
                    load_dotenv(config_file, override=True)
                    # 提取该服务的配置
                    self.configs[service_name] = self._load_service_config()

    def _load_service_config(self) -> Dict[str, Any]:
        """加载特定服务的配置"""
        config = {}
        # 先添加通用配置
        common_keys = ConfigManager.get_common_config_keys()
        for k in common_keys:
            config[k] = self.global_config[k]

        # 添加服务特定配置
        for k, v in os.environ.items():
            config[k] = v

        return config

    @staticmethod
    def get_common_config_keys() -> Set[str]:
        """获取通用配置键名"""
        return {
            'HOST', 'PORT', 'ENV_TYPE', 'MCP_LOGIN_URL',
            'OAUTH_USER_NAME', 'OAUTH_USER_PASSWORD',
            'LOG_LEVEL', 'MAX_RETRY_COUNT'
        }

    def get_service_config(self, service_name: str) -> Dict[str, Any]:
        """获取服务配置"""
        return self.configs.get(service_name, {})

    def get_global_config(self, k: str, default: Any = None) -> Any:
        """获取通用配置"""
        return self.global_config.get(k, default)

    def get_config_value(self, service_name: str, k: str, default: Any = None) -> Any:
        """获取特定服务的配置值"""
        service_config = self.get_service_config(service_name)
        return service_config.get(k, default)

    def list_available_services(self) -> List[str]:
        """列出可用服务"""
        return list(self.configs.keys())

    def update_service_config(self, service_name: str, updates: Dict[str, Any]):
        """更新服务配置"""
        if service_name not in self.configs:
            self.configs[service_name] = {}
        self.configs[service_name].update(updates)

        # 同时更新环境变量
        for k, v in updates.items():
            if v is not None:
                os.environ[k] = str(v)

    def create_session_config_manager(self, service_name: str):
        """为特定服务创建会话配置管理器"""
        try:
            from mcp_for_db.server.server_mysql.config.session_config import SessionConfigManager
            config = self.get_service_config(service_name)
            return SessionConfigManager(config if config else None)
        except ImportError:
            return None


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
    def _format_value(v: Any) -> str:
        """格式化配置值"""
        if isinstance(v, list):
            formatted_value = ','.join(str(v) for v in v)
        else:
            formatted_value = str(v)

        # 如果值包含特殊字符，添加引号
        if any(char in formatted_value for char in " #,\"'") and not formatted_value.startswith(('"', "'")):
            if '"' in formatted_value:
                formatted_value = f"'{formatted_value}'"
            else:
                formatted_value = f'"{formatted_value}"'

        return formatted_value


if __name__ == '__main__':
    config_manager = ConfigManager()

    print("可用的服务:", config_manager.list_available_services())
    print("MySQL 配置:")
    mysql_config = config_manager.get_service_config("mysql")
    for key, value in mysql_config.items():
        print(f"  {key} = {value}")

    print("DiFy 配置:")
    diFy_config = config_manager.get_service_config("dify")
    for key, value in diFy_config.items():
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

    # updates = {
    #     "MYSQL_PORT": "13309",
    #     "MYSQL_USER": "videx1",
    # }
    #
    # # 获取当前文件所在目录的绝对路径
    # root_dir = Path(__file__).parent.parent.parent.parent.parent
    # env_file = os.path.join(root_dir, "envs", "mysql.env")
    #
    # EnvFileManager.update_mysql_config(updates, env_file)
    # print("\n环境变量更新成功\n")
