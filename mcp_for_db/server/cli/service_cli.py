# import os
# import argparse
# from pathlib import Path
# """
# 快速服务添加脚本
#
# 使用方式：
#
# # 运行MySQL服务
# mcp-multi mysql
#
# # 运行Dify服务
# mcp-multi dify
#
# # 列出所有可用服务
# mcp-multi --list-services
#
# # 或使用服务专用命令
# mcp-mysql
# mcp-dify
#
# """
#
# def create_service_template(service_name: str):
#     """创建新服务模板"""
#     service_dir = Path(f"src/services/{service_name}_service")
#     service_dir.mkdir(parents=True, exist_ok=True)
#
#     # 创建服务文件
#     files = {
#         "__init__.py": "",
#         "mysql_server.py": f'''from typing import List, Dict, Any
# from mcp.types import Resource, Tool, Prompt
# from ...core.base_server import BaseMCPServer
#
# class {service_name.title()}MCPServer(BaseMCPServer):
#     """{\service_name.title()} MCP服务"""
#
#     def __init__(self, config: Dict[str, Any]):
#         super().__init__("{service_name}", config)
#
#     def get_tools(self) -> List[Tool]:
#         return []
#
#     def get_resources(self) -> List[Resource]:
#         return []
#
#     def get_prompts(self) -> List[Prompt]:
#         return []
# ''',
#         "tools/__init__.py": "",
#     }
#
#     for file_path, content in files.items():
#         full_path = service_dir / file_path
#         full_path.parent.mkdir(exist_ok=True)
#         full_path.write_text(content)
#
#     # 创建配置文件
#     config_file = Path(f"configs/{service_name}.env")
#     config_file.write_text(f"# {service_name.title()} service configuration\n")
#
#     print(f"Service template created for {service_name}")
#     print(f"Service directory: {service_dir}")
#     print(f"Config file: {config_file}")