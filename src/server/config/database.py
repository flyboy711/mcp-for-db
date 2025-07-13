import logging
import aiomysql
import asyncio
import hashlib
from typing import AsyncGenerator, Optional, Dict, Any
from server.config import MySQLConfigManager, EnvFileManager
from server.utils.logger import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="database.log")


def _get_config_hash(config: Dict[str, Any]) -> str:
    """生成配置哈希用于检测变更"""
    return hashlib.md5(str(config).encode('utf-8')).hexdigest()


class MySQLPoolManager:
    """数据库连接池管理器，支持配置变更检测和自动重连"""

    # 连接池状态常量
    STATE_UNINITIALIZED = 0
    STATE_ACTIVE = 1
    STATE_CLOSED = 2
    STATE_ERROR = 3

    def __init__(self, cfg_manager: MySQLConfigManager):
        """
        初始化连接池管理器
        :param cfg_manager: 数据库配置管理器实例
        """
        self._config_manager = cfg_manager
        self._pool: Optional[aiomysql.Pool] = None
        self._state = self.STATE_UNINITIALIZED
        self._config_hash = None
        self._successful_plugin = None

    @property
    def state(self) -> int:
        """返回当前连接池状态"""
        return self._state

    async def ensure_pool(self) -> None:
        """确保连接池已初始化并可用"""
        if self._state in (self.STATE_ACTIVE, self.STATE_ERROR):
            return

        if self._state == self.STATE_UNINITIALIZED:
            await self.initialize_pool()
        elif self._state == self.STATE_CLOSED:
            await self.initialize_pool()

    async def initialize_pool(self, max_retries: int = 3) -> None:
        """
        初始化或重置数据库连接池
        :param max_retries: 最大认证尝试次数
        """
        # 关闭现有连接池
        await self.close_pool()

        logger.info("初始化数据库连接池...")
        config = self._config_manager.get_config()
        new_hash = _get_config_hash(config)

        # 记录安全的配置信息（不含密码）
        safe_config = {k: v for k, v in config.items() if k != "password"}
        logger.debug(f"连接参数: {safe_config}")

        connection_params = {
            "host": config["host"],
            "port": config["port"],
            "user": config["user"],
            "password": config["password"],
            "db": config["database"],
            "autocommit": True,
            "minsize": 1,
            "maxsize": 10,
            "charset": "utf8mb4",
            "cursorclass": aiomysql.DictCursor
        }

        # 优先使用上次成功的认证插件或配置中的插件
        if self._successful_plugin:
            connection_params["auth_plugin"] = self._successful_plugin
            logger.info(f"使用上次成功的认证插件: {self._successful_plugin}")

        try:
            # 首次尝试连接
            self._pool = await aiomysql.create_pool(**connection_params)
            logger.info("数据库连接池初始化成功")
            self._state = self.STATE_ACTIVE
            self._config_hash = new_hash
            return
        except aiomysql.OperationalError as e:
            error_msg = str(e).lower()
            logger.warning(f"数据库连接异常: {e}")

            # 如果是认证问题且设置了重试，则尝试不同认证方式
            if "plugin" in error_msg and max_retries > 0:
                logger.info("尝试备用认证方案...")
                await self.try_alternative_auth(connection_params, max_retries)
            else:
                self._state = self.STATE_ERROR
                raise
        except Exception as e:
            logger.exception(f"数据库连接池初始化失败:{e}")
            self._state = self.STATE_ERROR
            raise

    async def try_alternative_auth(self, params: dict, max_retries: int) -> None:
        """尝试不同的认证方式"""
        plugins = [
            None,  # 自动协商
            "mysql_native_password",
            "caching_sha2_password",
            "sha256_password"
        ]

        for plugin in plugins:
            try:
                if plugin:
                    params["auth_plugin"] = plugin
                elif "auth_plugin" in params:
                    del params["auth_plugin"]

                logger.info(f"尝试认证插件: {plugin or 'auto'}")
                self._pool = await aiomysql.create_pool(**params)

                logger.info(f"使用插件 {plugin or 'auto'} 连接成功")
                self._state = self.STATE_ACTIVE
                self._successful_plugin = plugin

                # 如果成功使用特定插件，更新配置
                if plugin:
                    # 使用配置管理类而不是直接调用update_env_file
                    EnvFileManager.update({"MYSQL_AUTH_PLUGIN": plugin})

                return
            except Exception as e:
                logger.warning(f"插件 {plugin} 失败: {str(e)}")
                max_retries -= 1
                if max_retries <= 0:
                    break

        logger.critical("所有认证方式尝试失败")
        self._state = self.STATE_ERROR
        raise ConnectionError("无法连接数据库，请检查服务器配置")

    async def close_pool(self) -> None:
        """安全关闭数据库连接池"""
        if not self._pool or self._state in (self.STATE_CLOSED, self.STATE_UNINITIALIZED):
            return

        logger.info("关闭数据库连接池...")
        try:
            # 正确关闭连接池
            self._pool.close()
            await self._pool.wait_closed()
            logger.info("连接池已安全关闭")
        except RuntimeError as e:
            if "Event loop is closed" in str(e):
                logger.warning("无法安全关闭连接池：事件循环已结束")
            else:
                logger.warning(f"连接池关闭时发生运行时错误: {str(e)}")
        except asyncio.CancelledError:
            logger.warning("连接池关闭操作被取消")
        except Exception as e:
            logger.exception(f"关闭连接池时出错: {str(e)}")
        finally:
            self._pool = None
            self._state = self.STATE_CLOSED

    async def get_connection(self) -> AsyncGenerator[aiomysql.Connection, None]:
        """
        获取数据库连接
        添加了连接池状态检查和自动重连机制
        """
        # 确保连接池可用
        await self.ensure_pool()

        # 检查配置是否变更
        current_config = self._config_manager.get_config()
        current_hash = _get_config_hash(current_config)

        if current_hash != self._config_hash and self._state == self.STATE_ACTIVE:
            logger.warning("数据库配置已变更，正在重建连接池...")
            await self.initialize_pool()

        # 确保连接池不为空
        if not self._pool or self._state != self.STATE_ACTIVE:
            raise RuntimeError("数据库连接池不可用")

        # 获取连接
        async with self._pool.acquire() as conn:
            yield conn

    def is_healthy(self) -> bool:
        """检查连接池是否健康"""
        return self._state == self.STATE_ACTIVE and self._pool is not None


# 全局实例
config_manager = MySQLConfigManager()
mysql_pool_manager = MySQLPoolManager(config_manager)


# 测试代码
async def test_database_connection():
    """测试数据库连接，增加更多测试场景"""
    logger.info("\n=== 启动数据库连接测试 ===")

    try:
        # 场景1: 初始连接
        logger.info("测试场景1: 初始连接")
        await mysql_pool_manager.initialize_pool()
        logger.info("✅ 初始连接成功")

        # 场景2: 获取连接并执行查询
        logger.info("\n测试场景2: 获取连接并执行查询")
        async for conn in mysql_pool_manager.get_connection():
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT VERSION()")
                version = await cursor.fetchone()
                logger.info(f"✅ 数据库版本: {version['VERSION()']}")

        # 场景3: 模拟认证失败后的恢复
        logger.info("\n测试场景3: 模拟认证失败恢复")

        # 故意使用错误的插件
        original_plugin = config_manager.get_config().get("auth_plugin")
        EnvFileManager.update({"MYSQL_AUTH_PLUGIN": "invalid_plugin"})
        config_manager._load_config()  # 重新加载配置

        try:
            await mysql_pool_manager.initialize_pool()
        except ConnectionError:
            logger.info("✅ 成功检测到无效插件错误")

            # 恢复原始配置
            if original_plugin:
                EnvFileManager.update({"MYSQL_AUTH_PLUGIN": original_plugin})
            else:
                # 如果原始没有设置，删除该配置项
                EnvFileManager.update({"MYSQL_AUTH_PLUGIN": ""})

            config_manager._load_config()
            await mysql_pool_manager.initialize_pool()
            logger.info("✅ 成功恢复连接")

        # 场景4: 健康检查
        logger.info("\n测试场景4: 健康检查")
        if mysql_pool_manager.is_healthy():
            logger.info("✅ 连接池健康状态正常")
        else:
            logger.error("❌ 连接池健康状态异常")

    except Exception as e:
        logger.exception(f"❌ 测试失败: {str(e)}")
    finally:
        # 清理
        await mysql_pool_manager.close_pool()
        logger.info("=== 测试完成 ===")


if __name__ == "__main__":
    asyncio.run(test_database_connection())
