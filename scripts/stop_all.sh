#!/bin/bash

echo "🔴 Stopping all MCP services..."

# 发送停止命令
python -m src.cli.main stop

# 强制清理残留进程
echo "🧹 Cleaning up any remaining processes..."
pkill -f "mcp-mysql" 2>/dev/null || true
pkill -f "mcp-dify" 2>/dev/null || true

echo "✅ All services stopped"