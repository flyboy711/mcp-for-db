#!/bin/bash

# 默认启动 FastAPI 服务端
if [ "$1" = "server" ]; then
    echo "Starting FastAPI server..."
    exec python -m mcp_for_db.client.api

# 启动交互式客户端
elif [ "$1" = "client" ]; then
    echo "Starting CLI client..."
    exec python -m mcp_for_db.client.client

# 启动 MySQL 服务端
elif [ "$1" = "mysql" ]; then
    echo "Starting MySQL CLI server..."
    exec python -m mcp_for_db.server.cli.mysql_cli

# 启动 Dify 服务端
elif [ "$1" = "dify" ]; then
    echo "Starting Dify CLI server..."
    exec python -m mcp_for_db.server.cli.dify_cli

# 默认提示
else
    echo "Usage: docker run <image> [server|client|mysql|dify]"
    echo "Example:"
    echo "  docker run mcp-for-db server  # 启动 FastAPI 服务端"
    echo "  docker run mcp-for-db client  # 启动交互式客户端"
    exit 1
fi