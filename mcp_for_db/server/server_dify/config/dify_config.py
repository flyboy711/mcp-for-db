import hashlib
import os
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional

from dotenv import load_dotenv


class EnvironmentType(Enum):
    """环境类型"""
    DEVELOPMENT = 'development'
    PRODUCTION = 'production'


class DiFySessionConfig:
    """DiFy服务配置类"""

    def __init__(self, initial_config: Optional[Dict[str, Any]] = None, service_name: str = "mysql"):
        self.service_name = service_name
        self.server_config: Dict[str, Any] = {}
        self._config_hash = ''
        self._global_env_type: Optional[EnvironmentType] = None

        # 加载配置
        if initial_config is not None:
            self.server_config = initial_config.copy()
        else:
            # 从环境变量加载
            root_dir = Path(__file__).parent.parent.parent.parent.parent
            diFy_env_file = os.path.join(root_dir, "envs", "dify.env")
            load_dotenv(diFy_env_file, override=True)
            self.server_config["DIFY_BASE_URL"] = os.getenv('DIFY_BASE_URL')
            self.server_config["DIFY_API_KEY"] = os.getenv('DIFY_API_KEY')
            self.server_config["DIFY_DATASET_ID"] = os.getenv('DIFY_DATASET_ID')

        self._update_hash()

    def _update_hash(self) -> None:
        """更新配置哈希"""
        self._config_hash = hashlib.md5(str(sorted(self.server_config.items())).encode('utf-8')).hexdigest()

    def update(self, new_cfg: Dict[str, Any]) -> None:
        """更新配置"""
        self.server_config.update(new_cfg)
        if 'ENV_TYPE' in new_cfg:
            self._global_env_type = None
        self._update_hash()

    def get(self, k: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.server_config.get(k, default)

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self.server_config.copy()

    def get_config_hash(self) -> str:
        """获取配置哈希值"""
        return self._config_hash


if __name__ == '__main__':
    config = DiFySessionConfig()
    print(config.server_config.get('DIFY_BASE_URL'))
    print(config.server_config.get('DIFY_API_KEY'))
    print(config.server_config.get('DIFY_DATASET_ID'))
