import asyncio
import logging
from typing import Dict, Any
from server.config import SessionConfigManager
from server.config.database import DatabaseManager
from server.config.request_context import RequestContext
from server.utils.logger import get_logger, configure_logger

# 配置日志
logger = get_logger(__name__)
configure_logger(log_filename="resources.log")
logger.setLevel(logging.INFO)

# 模拟用户配置
USER_CONFIGS = {
    "user1": {
        "MYSQL_HOST": "rm-uf6pyrv408i5f0gap.mysql.rds.aliyuncs.com",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "onedba",
        "MYSQL_PASSWORD": "S9dKSCsdJm(mKd2",
        "MYSQL_DATABASE": "du_trade_timeout_db_3"
    },
    "user2": {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "13308",
        "MYSQL_USER": "videx",
        "MYSQL_PASSWORD": "password",
        "MYSQL_DATABASE": "tpch_tiny"
    }
}


async def execute_user_query(user_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """模拟用户执行查询操作"""
    logger.info(f"用户 {user_id} 开始执行查询")

    # 创建用户特定的会话配置
    session_config = SessionConfigManager(config)

    # 创建数据库管理器
    db_manager = DatabaseManager(session_config)

    # 设置请求上下文
    async with RequestContext(session_config, db_manager):
        # 模拟执行查询
        try:
            # 确保连接池初始化
            await db_manager.ensure_pool()

            # 获取当前数据库名称
            current_db = await db_manager.get_current_database()

            # 获取数据库信息
            db_info = await db_manager.get_database_info()

            # 执行一个简单查询
            result = await db_manager.execute_query("SELECT VERSION() AS version")
            version = result[0]['version'] if result else "Unknown"

            return {
                "user_id": user_id,
                "current_database": current_db,
                "db_info": db_info,
                "mysql_version": version,
                "status": "success"
            }
        except Exception as e:
            logger.error(f"用户 {user_id} 查询失败: {str(e)}")
            return {
                "user_id": user_id,
                "error": str(e),
                "status": "failed"
            }
        finally:
            await db_manager.close_pool()


async def run_concurrent_users():
    """并发运行多个用户查询"""
    tasks = []

    # 为每个用户创建任务
    for user_id, config in USER_CONFIGS.items():
        task = asyncio.create_task(execute_user_query(user_id, config))
        tasks.append(task)

    # 等待所有任务完成
    results = await asyncio.gather(*tasks)

    # 输出结果
    logger.info("\n=== 测试结果 ===")
    for result in results:
        if result['status'] == 'success':
            logger.info(f"用户 {result['user_id']} 测试成功")
            logger.info(f"  当前数据库: {result['current_database']}")
            logger.info(f"  MySQL版本: {result['mysql_version']}")
            logger.info(f"  数据库状态: {result['db_info']['status']}")
        else:
            logger.error(f"用户 {result['user_id']} 测试失败: {result['error']}")

    logger.info("=== 测试完成 ===")


def test_multi_user_context():
    """测试多用户上下文隔离"""
    logger.info("开始多用户上下文隔离测试")

    # 创建事件循环
    loop = asyncio.get_event_loop()

    try:
        # 运行并发测试
        loop.run_until_complete(run_concurrent_users())
    except Exception as e:
        logger.error(f"测试失败: {str(e)}")
    finally:
        # 关闭事件循环
        loop.close()
        logger.info("事件循环已关闭")


if __name__ == "__main__":
    test_multi_user_context()
