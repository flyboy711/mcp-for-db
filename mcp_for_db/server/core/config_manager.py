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

    def update_service_config(self, service_name: str, update: Dict[str, Any]):
        """更新服务配置"""
        if service_name not in self.configs:
            self.configs[service_name] = {}
        self.configs[service_name].update(update)

        # 同时更新环境变量
        for k, v in update.items():
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
    """环境文件管理器"""

    @staticmethod
    def update_config(update: Dict[str, Any], env_type: str, env_path: str = None) -> None:
        """更新服务配置文件"""
        if env_path is None:
            root_dir = Path(__file__).parent.parent.parent
            env_files = {
                "mysql": "mysql.env",
                "common": "common.env",
                "dify": "dify.env"
            }
            if env_type in env_files:
                env_path = root_dir / "envs" / env_files[env_type]
            else:
                raise ValueError(f"不支持的环境类型: {env_type}")

        EnvFileManager.update_config_file(update, str(env_path))

    @staticmethod
    def update_config_file(update: Dict[str, Any], env_path: str) -> None:
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

            # 跳过空行和注释行
            if not stripped_line or stripped_line.startswith("#"):
                new_lines.append(line)
                continue

            # 解析配置行
            parsed_result = EnvFileManager._parse_config_line(line)
            if parsed_result:
                k, v, comment = parsed_result

                if k in update:
                    # 更新这个配置项
                    formatted_value = EnvFileManager._format_value(update[k])
                    if comment:
                        new_line = f"{k}={formatted_value} {comment}\n"
                    else:
                        new_line = f"{k}={formatted_value}\n"
                    new_lines.append(new_line)
                    updated_keys.add(k)
                else:
                    # 保持原有配置不变
                    new_lines.append(line)
            else:
                # 不是有效的配置行，保持原样
                new_lines.append(line)

        # 添加新的配置项
        for k, v in update.items():
            if k not in updated_keys:
                formatted_value = EnvFileManager._format_value(v)
                new_lines.append(f"{k}={formatted_value}\n")

        # 写入文件
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    @staticmethod
    def _parse_config_line(line: str) -> tuple[str, str, str] | None:
        """解析配置行，返回 (key, value, comment) 或 None

        处理各种情况：
        - KEY=value
        - KEY="quoted value"
        - KEY='quoted value'
        - KEY=value # comment
        - KEY="quoted value" # comment
        """
        line = line.rstrip('\n\r')

        # 必须包含等号
        if '=' not in line:
            return None

        # 分离键和值部分
        key_part, rest = line.split('=', 1)
        k = key_part.strip()

        if not k:
            return None

        # 解析值和注释
        v, comment = EnvFileManager._parse_value_and_comment(rest)

        return k, v, comment

    @staticmethod
    def _parse_value_and_comment(value_part: str) -> tuple[str, str]:
        """解析值和注释部分

        Args:
            value_part: 等号后面的部分

        Returns:
            tuple[str, str]: (value, comment)
        """
        value_part = value_part.strip()

        if not value_part:
            return "", ""

        # 情况1: 以引号开始的值
        if value_part.startswith('"'):
            return EnvFileManager._parse_quoted_value(value_part, '"')
        elif value_part.startswith("'"):
            return EnvFileManager._parse_quoted_value(value_part, "'")

        # 情况2: 无引号的值，查找注释
        comment_pos = value_part.find(' #')
        if comment_pos != -1:
            v = value_part[:comment_pos].strip()
            comment = value_part[comment_pos:].strip()
            return v, comment

        # 情况3: 纯值，无注释
        return value_part, ""

    @staticmethod
    def _parse_quoted_value(value_part: str, quote_char: str) -> tuple[str, str]:
        """解析带引号的值

        Args:
            value_part: 以引号开始的字符串
            quote_char: 引号字符 (" 或 ')

        Returns:
            tuple[str, str]: (value, comment)
        """
        # 查找匹配的结束引号
        pos = 1  # 跳过开始引号
        while pos < len(value_part):
            if value_part[pos] == quote_char:
                # 找到结束引号
                quoted_value = value_part[1:pos]  # 提取引号内的值
                remaining = value_part[pos + 1:].strip()  # 引号后的部分

                # 检查是否有注释
                if remaining.startswith(' #') or remaining.startswith('#'):
                    comment = remaining if remaining.startswith('#') else remaining
                    return quoted_value, comment
                elif remaining == "":
                    return quoted_value, ""
                else:
                    # 引号后有其他内容，可能是格式错误，但我们尽量处理
                    return quoted_value, ""
            elif value_part[pos] == '\\' and pos + 1 < len(value_part):
                # 跳过转义字符
                pos += 2
            else:
                pos += 1

        # 没找到结束引号，把整个当作值
        return value_part, ""

    @staticmethod
    def _format_value(v: Any) -> str:
        """格式化配置值"""
        if isinstance(v, list):
            formatted_value = ','.join(str(item) for item in v)
        else:
            formatted_value = str(v)

        # 判断是否需要加引号
        needs_quotes = any(char in formatted_value for char in ' #,"\'\n\r\t')

        if needs_quotes:
            # 选择合适的引号字符
            if '"' in formatted_value and "'" not in formatted_value:
                return f"'{formatted_value}'"
            elif "'" in formatted_value and '"' not in formatted_value:
                return f'"{formatted_value}"'
            elif '"' in formatted_value and "'" in formatted_value:
                # 两种引号都有，转义双引号
                escaped_value = formatted_value.replace('"', '\\"')
                return f'"{escaped_value}"'
            else:
                # 默认使用双引号
                return f'"{formatted_value}"'

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

    updates = {
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
    }

    EnvFileManager.update_config(updates, "mysql")
    print("\n环境变量更新成功\n")
