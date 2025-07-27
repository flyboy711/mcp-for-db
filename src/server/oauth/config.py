from pydantic_settings import BaseSettings, SettingsConfigDict


class OAuthConfig(BaseSettings):
    """OAuth配置类"""

    # 客户端配置
    CLIENT_ID: str = "mysql-mcp-client"
    CLIENT_SECRET: str = "mysql-mcp-secret"  # 使用一个固定的密钥

    # Token配置
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Token加密配置
    TOKEN_SECRET_KEY: str = "mysql-mcp-server-pro-secret-key"  # 使用一个固定的密钥
    TOKEN_ALGORITHM: str = "HS256"

    # 允许的授权类型
    GRANT_TYPES: list[str] = ["password", "refresh_token"]

    model_config = SettingsConfigDict(
        extra="ignore",  # 忽略未定义的字段
        env_file=".env",
        case_sensitive=True
    )


# 创建配置实例
oauth_config = OAuthConfig()
