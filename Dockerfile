FROM python:3.12-slim

WORKDIR /app

# 安装依赖
COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 设置环境变量 (示例值，请替换为实际值)
ENV MYSQL_HOST="host.docker.internal"
ENV MYSQL_PORT="13308"
ENV MYSQL_USER="videx"
ENV MYSQL_PASSWORD="password"
ENV MYSQL_DATABASE="tpch_tiny"

# 暴露 FastAPI 端口
EXPOSE 8000

# 启动脚本 (支持服务端或客户端)
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]