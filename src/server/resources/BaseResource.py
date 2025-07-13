import logging
from typing import List, Type, ClassVar, Dict
from urllib.parse import urlparse
from pydantic.networks import AnyUrl
from mcp.types import Resource
from server.utils.logger import configure_logger, get_logger

logger = get_logger(__name__)
configure_logger(log_level=logging.INFO, log_filename="resources.log")


class ResourceRegistry:
    """资源注册表，用于管理所有资源实例"""
    _resources: ClassVar[Dict[str, 'BaseResource']] = {}

    @classmethod
    def register(cls, resource_class: Type['BaseResource']) -> Type['BaseResource']:
        """注册资源实例"""
        resource = resource_class()
        logger.info(f"注册资源: {resource.name} (URI: {resource.uri})")
        cls._resources[resource.name] = resource
        return resource_class

    @classmethod
    async def get_resource(cls, uri: AnyUrl) -> str:
        """获取资源内容"""
        logger.info(f"请求资源: {uri}")
        parsed = urlparse(str(uri))
        base_uri = f"{parsed.scheme}://{parsed.netloc}"

        # 优先尝试精确匹配
        for resource in cls._resources.values():
            if resource.uri == uri:
                return await resource.read_resource(uri)

        # 尝试前缀匹配
        for resource in cls._resources.values():
            if str(resource.uri).startswith(base_uri):
                return await resource.read_resource(uri)

        logger.error(f"未找到资源: {uri}，已注册资源: {[r.uri for k, r in cls._resources.items()]}")
        raise ValueError(f"未注册的资源: {uri}")

    @classmethod
    async def get_all_resources(cls) -> List[Resource]:
        """获取所有资源的描述"""
        result = []
        for resource in cls._resources.values():
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

    def __init_subclass__(cls, **kwargs):
        """子类初始化时自动注册到prompt注册表"""
        super().__init_subclass__(**kwargs)
        if cls.name:  # 只注册有uri的资源
            ResourceRegistry.register(cls)

    async def get_resource_descriptions(self) -> List[Resource]:
        """获取资源描述，子类必须实现"""
        raise NotImplementedError

    async def read_resource(self, uri: AnyUrl) -> str:
        """读取资源内容，子类必须实现"""
        raise NotImplementedError
