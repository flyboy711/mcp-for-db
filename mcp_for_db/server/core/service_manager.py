import os.path
from pathlib import Path
from typing import Dict, Optional, List, Type
from mcp_for_db.server.core import ConfigManager
from mcp_for_db.server.core import BaseMCPServer


class ServiceManager:
    """多 MCP 服务管理器"""

    def __init__(self, config_dir: str = os.path.join(Path(__file__).parent.parent.parent.parent, "envs")):
        self.config_manager = ConfigManager(config_dir)
        self.services: Dict[str, BaseMCPServer] = {}
        self.service_classes: Dict[str, Type[BaseMCPServer]] = {}
        self._register_default_services()

    def _register_default_services(self):
        """注册默认服务"""
        try:
            from mcp_for_db.server.server_mysql import MySQLMCPServer
            self.service_classes["mysql"] = MySQLMCPServer
        except ImportError:
            pass

        try:
            from mcp_for_db.server.server_dify import DiFyMCPServer
            self.service_classes["dify"] = DiFyMCPServer
        except ImportError:
            pass

    def register_service(self, name: str, service_class: Type[BaseMCPServer]):
        """注册新的服务类型"""
        self.service_classes[name] = service_class

    def create_service(self, service_name: str) -> Optional[BaseMCPServer]:
        """创建特定服务实例"""
        if service_name not in self.service_classes:
            available = ", ".join(self.service_classes.keys())
            raise ValueError(f"Unknown service: {service_name}. Available: {available}")

        # 检查是否已有实例
        if service_name in self.services:
            return self.services[service_name]

        # 创建新实例
        service_class = self.service_classes[service_name]
        service = service_class(self.config_manager)
        self.services[service_name] = service

        return service

    def list_available_services(self) -> List[str]:
        """列出可用服务"""
        return list(self.service_classes.keys())

    def list_configured_services(self) -> List[str]:
        """列出已配置的服务"""
        return self.config_manager.list_available_services()

    def get_service_config(self, service_name: str) -> Dict:
        """获取服务配置"""
        return self.config_manager.get_service_config(service_name)


if __name__ == "__main__":
    service_manager = ServiceManager()
    print(service_manager.list_available_services())
    print(service_manager.list_configured_services())
    print(service_manager.get_service_config("mysql"))
    print(service_manager.service_classes)
    print(service_manager.services)
    print(service_manager.create_service("mysql"))
