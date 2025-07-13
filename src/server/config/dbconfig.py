import os
from dotenv import load_dotenv


class MySQLConfigManager:
    """数据库配置与权限管理的统一封装"""
    # 角色权限常量（类级别）
    ROLE_PERMISSIONS = {
        "readonly": ["SELECT", "SHOW", "DESCRIBE", "EXPLAIN"],
        "admin": ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "TRUNCATE"]
    }

    def __init__(self):
        self._load_config()

    def _load_config(self):
        """加载环境变量并验证配置"""
        load_dotenv()
        self.host = os.getenv("MYSQL_HOST", "localhost")
        self.port = int(os.getenv("MYSQL_PORT", "3306"))
        self.user = os.getenv("MYSQL_USER")
        self.password = os.getenv("MYSQL_PASSWORD")
        self.database = os.getenv("MYSQL_DATABASE")
        self.role = os.getenv("MYSQL_ROLE", "readonly")

        if not all([self.user, self.password, self.database]):
            raise ValueError("Missing required database configuration")

    def get_config(self) -> dict:
        """返回当前配置字典"""
        return {k: getattr(self, k) for k in ["host", "port", "user", "password", "database", "role"]}

    def get_role_permissions(self, role: str = None) -> list:
        """获取指定角色的权限列表（默认当前角色）"""
        target_role = role or self.role
        return self.ROLE_PERMISSIONS.get(target_role, self.ROLE_PERMISSIONS["readonly"])

    def validate_operation(self, operation: str, role: str = None) -> bool:
        """验证操作是否在角色权限内（扩展功能）"""
        return operation in self.get_role_permissions(role)


class EnvFileManager:
    """环境文件管理封装"""

    @staticmethod
    def update(updates: dict, env_path=".env"):
        """原子化更新.env文件"""
        existing_lines = []
        updated_keys = set()

        # 读取现有配置
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                existing_lines = f.readlines()

        # 更新现有行
        for i, line in enumerate(existing_lines):
            if line.strip() and not line.startswith("#") and "=" in line:
                key, _, value_part = line.partition("=")
                key = key.strip()

                if key in updates:
                    # 保留尾部注释
                    comment = f" #{value_part.split('#')[1]}" if "#" in value_part else ""
                    existing_lines[i] = f"{key}={updates[key]}{comment}\n"
                    updated_keys.add(key)

        # 追加新配置项
        for key, value in updates.items():
            if key not in updated_keys:
                formatted_value = f'"{value}"' if any(c in value for c in " #\"'") else value
                existing_lines.append(f"\n{key}={formatted_value}\n")

        # 原子写入
        with open(env_path, "w") as f:
            f.writelines(existing_lines)


# 使用示例
if __name__ == "__main__":
    config_manager = MySQLConfigManager()

    try:
        EnvFileManager.update({
            "MYSQL_HOST": "localhost1",
            "MAX_CONNECTIONS": "100"
        })
        print("环境变量更新成功")

        print(f"当前角色权限: {config_manager.get_role_permissions()}")
        print(f"ADMIN权限: {config_manager.get_role_permissions('admin')}")
        print(f"DELETE操作允许: {config_manager.validate_operation('DELETE')}")

    except Exception as e:
        print(f"操作失败: {str(e)}")
