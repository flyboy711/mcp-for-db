"""针对 stdio 通信机制配置的环境变量，服务端进行分发处理"""

import os
from pathlib import Path
from typing import Dict, Any, List

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.core import EnvFileManager
from mcp_for_db.server.shared.utils import get_logger

logger = get_logger(__name__)
logger.setLevel(LOG_LEVEL)


class EnvDistributor:
    """环境变量分发器: 将 stdio 模式的环境变量分发到各个服务配置文件"""

    # 定义各服务的环境变量映射
    SERVICE_ENV_MAPPING = {
        'mysql': {
            'prefix': 'MYSQL_',
            'env_file': 'mysql.env',
            'required_vars': {'MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DATABASE'},
            'optional_vars': {
                'MYSQL_DB_POOL_ENABLED', 'MYSQL_DB_POOL_MIN_SIZE', 'MYSQL_DB_POOL_MAX_SIZE',
                'MYSQL_DB_POOL_RECYCLE', 'MYSQL_DB_POOL_MAX_LIFETIME', 'MYSQL_DB_POOL_ACQUIRE_TIMEOUT',
                'MYSQL_ALLOWED_RISK_LEVELS', 'MYSQL_ENABLE_QUERY_CHECK', 'MYSQL_ENABLE_DATABASE_ISOLATION',
                'MYSQL_DATABASE_ACCESS_LEVEL', 'MYSQL_MAX_SQL_LENGTH', 'MYSQL_BLOCKED_PATTERNS',
                'MYSQL_DB_AUTH_PLUGIN', 'MYSQL_DB_CONNECTION_TIMEOUT'
            }
        },
        'dify': {
            'prefix': 'DIFY_',
            'env_file': 'dify.env',
            'required_vars': {'DIFY_BASE_URL', 'DIFY_API_KEY', 'DIFY_DATASET_ID'},
            'optional_vars': {'DIFY_TIMEOUT', 'DIFY_MAX_RETRIES'}
        },
        'common': {
            'prefix': 'COMMON_',
            'env_file': 'common.env',
            'required_vars': set(),
            'optional_vars': {'LOG_LEVEL', 'MAX_WORKERS'}
        }
    }

    def __init__(self, envs_dir: str = None):
        """初始化分发器
        Args:
            envs_dir: envs目录路径，默认自动检测
        """
        if envs_dir is None:
            self.envs_dir = Path(__file__).parent.parent.parent / "envs"
        else:
            self.envs_dir = Path(envs_dir)

        # 确保 envs 目录存在
        self.envs_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"环境变量分发器初始化完成，envs目录: {self.envs_dir}")

    def distribute_env_vars(self, enabled_services: List[str] = None, env_vars: Dict[str, str] = None):
        """分发环境变量到各服务配置文件
        Args:
             enabled_services: 启动的服务列表，如 ['mysql', 'dify']。不能为 Node
            env_vars: 环境变量字典，默认使用os.environ

        Returns:
            Dict[str, Dict[str, Any]]: 各服务分发的配置信息
        """
        if env_vars is None:
            env_vars = dict(os.environ)

        if enabled_services is None:
            logger.warning("⚠️：可用服务不能缺失！")
            raise "请提供有效的服务。"

        logger.info(f"开始分发环境变量，共 {len(env_vars)} 个变量")

        distribution_result = {}

        for service_name in enabled_services:
            config = self.SERVICE_ENV_MAPPING[service_name]
            # 提取特定服务的环境变量并直接替换更新
            service_vars = EnvDistributor._extract_service_vars(env_vars, config)

            if service_vars:
                # 刷新服务配置文件
                env_file_path = self.envs_dir / config['env_file']
                EnvDistributor.update_service_config(service_name, service_vars, env_file_path)
                distribution_result[service_name] = service_vars

                logger.info(f"服务 {service_name} 分发了 {len(service_vars)} 个配置项")
            else:
                logger.debug(f"服务 {service_name} 没有找到相关环境变量")

    @staticmethod
    def _extract_service_vars(env_vars: Dict[str, str], service_config: Dict) -> Dict[str, Any]:
        """提取特定服务的环境变量"""
        service_vars = {}
        prefix = service_config['prefix']
        all_service_vars = service_config['required_vars'] | service_config['optional_vars']

        # 按前缀匹配
        for key, value in env_vars.items():
            if key.startswith(prefix) and key in all_service_vars:
                service_vars[key] = value

        # 检查必需变量
        missing_required = service_config['required_vars'] - set(service_vars.keys())
        if missing_required:
            logger.warning(f"缺少必需的环境变量: {missing_required}")

        return service_vars

    @staticmethod
    def update_service_config(service_name: str, service_vars: Dict[str, Any], env_file_path: Path):
        """刷新服务配置文件"""
        try:
            logger.debug(f"更新 {service_name} 配置文件: {env_file_path}")
            EnvFileManager.update_config_file(service_vars, str(env_file_path))
            logger.info(f"{service_name} 配置文件更新成功")
        except Exception as e:
            logger.error(f"更新 {service_name} 配置文件失败: {e}")
            raise

    def validate_stdio_config(self, enabled_services: List[str] = None, env_vars: Dict[str, str] = None) -> Dict[
        str, bool]:
        """验证 stdio 模式的配置完整性

        Args:
            enabled_services: 启动的服务列表，如 ['mysql', 'dify']。不能为 Node
            env_vars: 环境变量字典，默认使用os.environ

        Returns:
            Dict[str, bool]: 各服务配置验证结果 {service_name: is_valid}
        """
        if env_vars is None:
            env_vars = dict(os.environ)

        # 如果没有指定启动服务，默认验证所有服务
        if enabled_services is None:
            logger.warning("⚠️：可用服务不能缺失！")
            return {"is_valid": False}

        # 验证启动服务列表的有效性
        invalid_services = set(enabled_services) - set(self.SERVICE_ENV_MAPPING.keys())
        if invalid_services:
            logger.warning(f"未知的服务名称: {invalid_services}")
            # 过滤掉无效的服务名
            enabled_services = [s for s in enabled_services if s in self.SERVICE_ENV_MAPPING]

        logger.info(f"验证 {len(enabled_services)} 个启动服务的配置: {enabled_services}")

        validation_result = {}

        # 只验证启动的服务
        for service_name in enabled_services:
            config = self.SERVICE_ENV_MAPPING[service_name]
            required_vars = config['required_vars']
            missing_vars = required_vars - set(env_vars.keys())

            # 返回简单的布尔值
            is_valid = len(missing_vars) == 0
            validation_result[service_name] = is_valid

            # 详细的日志信息
            present_vars = [var for var in required_vars if var in env_vars]

            if missing_vars:
                logger.warning(f"服务 {service_name} 配置不完整")
                logger.warning(f"缺少必需参数: {list(missing_vars)}")
                if present_vars:
                    logger.info(f"已配置参数: {present_vars}")
            else:
                logger.info(f"服务 {service_name} 配置验证通过")
                logger.debug(f"必需参数: {list(required_vars)}")

        # 输出验证汇总
        valid_count = sum(validation_result.values())
        total_count = len(validation_result)
        logger.info(f"配置验证完成: {valid_count}/{total_count} 个服务配置有效")

        return validation_result
