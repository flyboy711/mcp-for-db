import logging
from typing import List, Type, ClassVar, Dict
from urllib.parse import urlparse
from pydantic.networks import AnyUrl
from mcp.types import Resource
from mcp_for_db.server.shared.utils import configure_logger, get_logger

logger = get_logger(__name__)
configure_logger(log_filename="resources.log")
logger.setLevel(logging.WARNING)


class ResourceRegistry:
    """资源注册表，用于管理所有资源实例"""
    _resources: ClassVar[Dict[str, 'BaseResource']] = {}

    @classmethod
    def register(cls, resource_class: Type['BaseResource']):
        """注册资源实例"""
        resource = resource_class()
        logger.info(f"注册资源: {resource.name} (URI: {resource.uri})")
        cls._resources[str(resource.uri)] = resource

    @classmethod
    def register_instance(cls, resource: 'BaseResource'):
        """手动注册资源实例"""
        uri_str = str(resource.uri)
        logger.info(f"注册资源实例: {resource.name} (URI: {uri_str})")
        cls._resources[uri_str] = resource

    @classmethod
    async def get_resource(cls, uri: AnyUrl) -> str:
        """获取资源内容"""
        logger.info(f"请求资源: {uri}")
        parsed = urlparse(str(uri))
        uri_str = f"{parsed.scheme}://{parsed.netloc}/{parsed.path}"
        path_parts = parsed.path.strip('/').split('/')

        if not path_parts or not path_parts[0]:
            raise ValueError(f"无效的URI格式: {uri_str}，未指定表名")

        # 优先尝试精确匹配
        for resource in cls._resources.values():
            if str(resource.uri) == uri_str:
                return await resource.read_resource(uri)

        # 尝试后缀匹配
        for resource in cls._resources.values():
            if str(resource.uri).endswith(path_parts[0]):
                return await resource.read_resource(uri)

        logger.error(f"未找到资源: {uri}，已注册资源: {[r.uri for k, r in cls._resources.items()]}")
        raise ValueError(f"未注册的资源: {uri}")

    @classmethod
    async def get_all_resources(cls) -> List[Resource]:
        """获取所有资源的描述"""
        result = []
        # 创建资源副本避免在迭代过程中修改原字典:扫描库时还会注册表资源
        resources_copy = list(cls._resources.values())
        for resource in resources_copy:
            try:
                logger.info(f"获取 {resource.name} 的资源描述")
                descriptions = await resource.get_resource_descriptions()
                result.extend(descriptions)
                logger.debug(f"{resource.name} 提供了 {len(descriptions)} 个资源描述")
            except Exception as e:
                logger.error(f"获取 {resource.name} 的描述失败: {str(e)}", exc_info=True)
        return result


class BaseResource:
    """资源基类"""
    name: str = ""
    description: str = ""
    uri: AnyUrl
    mimeType: str = "text/plain"
    auto_register: bool = True

    def __init_subclass__(cls, **kwargs):
        """子类初始化时自动注册到资源注册表"""
        super().__init_subclass__(**kwargs)
        if cls.auto_register and cls.uri is not None:  # 只注册有 uri 的资源
            ResourceRegistry.register(cls)

    async def get_resource_descriptions(self) -> List[Resource]:
        """获取资源描述，子类必须实现"""
        raise NotImplementedError

    async def read_resource(self, uri: AnyUrl) -> str:
        """读取资源内容，子类必须实现"""
        raise NotImplementedError
