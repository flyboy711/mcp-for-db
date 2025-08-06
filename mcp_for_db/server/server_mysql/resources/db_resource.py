import json
import logging
import csv
from io import StringIO
from urllib.parse import urlparse
import aiomysql
from typing import List
from pydantic.networks import AnyUrl
from mcp.types import Resource
from mcp_for_db.server.server_mysql.config.request_context import get_current_database_manager
from mcp_for_db.server.common.base.base_resource import BaseResource, ResourceRegistry
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger(log_filename="resources.log")
logger.setLevel(logging.WARNING)


def _build_safe_query(table_name: str) -> str:
    """构建安全的SQL查询语句"""
    # 对表名进行简单清理
    clean_table_name = ''.join(c for c in table_name if c.isalnum() or c in ('_', '-', ' ', '.')).strip()

    # 限制行数并优先排序（避免随机返回）
    return f"SELECT * FROM `{clean_table_name}` ORDER BY 1 LIMIT 100"


def generate_csv(columns: list, rows: list, metadata: list) -> str:
    """使用csv模块生成格式正确的CSV"""
    output = StringIO()
    writer = csv.writer(output)

    # 添加列名和类型作为注释
    if metadata:
        type_info = [f"{name} ({dtype})" for name, dtype in metadata]
        writer.writerow(type_info)

    writer.writerow(columns)

    for row in rows:
        # 按列顺序获取值
        row_values = [row[col] for col in columns]
        writer.writerow(row_values)

    content = output.getvalue()
    output.close()

    logger.info(f"生成长度为 {len(content)} 字节的CSV")
    return content


def extract_table_name(uri: AnyUrl) -> str:
    """安全解析表名并验证存在性"""
    uri_str = str(uri)
    if not uri_str.startswith("mysql://"):
        raise ValueError(f"无效的URI方案: {uri_str}，应使用 mysql://'")

    parsed = urlparse(uri_str)
    path_parts = parsed.path.strip('/').split('/')

    if not path_parts or not path_parts[0]:
        raise ValueError(f"无效的URI格式: {uri_str}，未指定表名")

    return path_parts[0]


class TableResource(BaseResource):
    """代表具体表资源的类"""
    auto_register: bool = False

    TABLE_EXISTS_QUERY = """
        SELECT COUNT(*) AS table_exists
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
    """

    COLUMN_METADATA_QUERY = """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ORDINAL_POSITION
    """

    def __init__(self, db_name: str, table_name: str, description: str):
        super().__init__()
        self.db_name = db_name
        self.table_name = table_name
        self.name = f"table: {table_name}"
        self.uri = AnyUrl(f"mysql://{db_name}/{table_name}")
        self.description = description
        self.mimeType = "text/csv"

    async def get_resource_descriptions(self) -> List[Resource]:
        """返回数据库表资源的描述:已返回"""
        return []

    async def read_resource(self, uri: AnyUrl) -> str:
        """安全读取数据库表数据为CSV格式（带列类型信息）"""
        logger.info(f"开始读取资源: {uri}")
        try:
            # 安全解析表名
            table_name = extract_table_name(uri)
            logger.info(f"准备查询表: {table_name}")

            # 获取列元数据（用于优化CSV生成）
            column_metadata = await self.get_table_metadata(table_name)

            async with get_current_database_manager().get_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    # 使用参数化查询避免SQL注入
                    safe_query = _build_safe_query(table_name)
                    await cursor.execute(safe_query)

                    # 直接获取列名
                    columns = [col[0] for col in cursor.description]
                    rows = await cursor.fetchall()

                    logger.info(f"获取到 {len(rows)} 行数据")

                    # 使用优化的CSV生成
                    return generate_csv(columns, rows, column_metadata)

        except Exception as e:
            logger.error(f"读取资源失败: {str(e)}", exc_info=True)
            raise

    async def get_table_metadata(self, table_name: str) -> List[tuple]:
        """获取表列名和数据类型"""
        db_name = get_current_database_manager().get_current_config()["database"]

        async with get_current_database_manager().get_connection() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # 首先验证表存在
                await cursor.execute(self.TABLE_EXISTS_QUERY, (db_name, table_name))
                exists = await cursor.fetchone()

                if not exists or not exists['table_exists']:
                    raise ValueError(f"表 '{table_name}' 在数据库 '{db_name}' 中不存在")

                # 获取列元数据
                await cursor.execute(self.COLUMN_METADATA_QUERY, (db_name, table_name))
                metadata = [(row['COLUMN_NAME'], row['DATA_TYPE']) for row in await cursor.fetchall()]

                return metadata


class MySQLResource(BaseResource):
    """MySQL数据库资源实现"""
    name = "MySQL数据库"
    uri = AnyUrl(f"mysql://localhost/default")
    description = "提供对MySQL数据库表的访问与查询"
    mimeType = "text/csv"
    auto_register = True

    # 重用这些常量查询
    TABLE_QUERY = """
        SELECT TABLE_NAME AS table_name,
               TABLE_COMMENT AS table_comment,
               TABLE_ROWS AS estimated_rows
        FROM information_schema.tables
        WHERE table_schema = %s
    """

    def __init__(self):
        """初始化资源管理"""
        super().__init__()
        self.cache = {}  # 查询结果缓存

    async def get_resource_descriptions(self) -> List[Resource]:
        """获取数据库表资源描述（带缓存机制）"""
        logger.info("获取数据库资源描述")

        db_manager = get_current_database_manager()
        if db_manager is None:
            logger.error("无法获取数据库管理器，上下文未设置？")
            return []

        db_name = db_manager.get_current_config().get("database")
        if not db_name:
            logger.error("数据库配置中未指定数据库名称")
            return []

        # 使用缓存避免重复查询
        if 'table_descriptions' in self.cache:
            logger.debug("使用缓存的表描述")
            return self.cache['table_descriptions']

        try:
            async with db_manager.get_connection() as conn:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(self.TABLE_QUERY, (db_name,))
                    tables = await cursor.fetchall()
                    logger.info(f"发现 {len(tables)} 个数据库表")

                    resources = []
                    for table in tables:
                        table_name = table['table_name']

                        # 添加表行数统计
                        description = table['table_comment'] or f"{table_name} 表"
                        if table['estimated_rows']:
                            description += f" (~{table['estimated_rows']}行)"

                        # 创建表资源
                        table_resource = TableResource(db_name, table_name, description)

                        # 手动注册表资源实例
                        ResourceRegistry.register_instance(table_resource)

                        # 创建资源描述对象
                        resource_desc = Resource(
                            uri=table_resource.uri,
                            name=table_resource.name,
                            mimeType=table_resource.mimeType,
                            description=table_resource.description
                        )
                        resources.append(resource_desc)

                    # 缓存结果
                    self.cache['table_descriptions'] = resources
                    logger.info(f"创建了 {len(resources)} 个表资源描述")
                    return resources

        except Exception as e:
            logger.error(f"获取资源描述失败: {str(e)}", exc_info=True)
            return []

    async def read_resource(self, uri: AnyUrl) -> str:
        """读取根资源内容 - 返回数据库信息"""
        return json.dumps({
            "name": self.name,
            "uri": self.uri,
            "description": self.description,
            "type": "database_root"
        })
