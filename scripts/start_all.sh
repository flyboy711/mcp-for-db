#!/bin/bash

# 启动MCP服务的脚本

echo "🚀 Starting MCP Services..."

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认配置
DEFAULT_MYSQL_PORT=3000
DEFAULT_DIFY_PORT=3001
DEFAULT_HOST="0.0.0.0"

# 参数解析
MYSQL_PORT=$DEFAULT_MYSQL_PORT
DIFY_PORT=$DEFAULT_DIFY_PORT
HOST=$DEFAULT_HOST
MYSQL_ONLY=false
DIFY_ONLY=false
ENVFILE=""
BACKGROUND=false

# 获取脚本所在目录和项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "📂 Script directory: $SCRIPT_DIR"
echo "📂 Project root: $PROJECT_ROOT"

# 显示帮助信息
show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help           Show this help message"
    echo "  --mysql-port PORT    MySQL service port (default: 3000)"
    echo "  --dify-port PORT     Dify service port (default: 3001)"
    echo "  --host HOST          Host to bind (default: 0.0.0.0)"
    echo "  --mysql-only         Start only MySQL service"
    echo "  --dify-only          Start only Dify service"
    echo "  --envfile FILE       Custom environment file path"
    echo "  --background         Run in background"
    echo "  --stop               Stop running services"
    echo "  --status             Show service status"
    echo ""
    echo "Examples:"
    echo "  $0                          # Start both services with default ports"
    echo "  $0 --mysql-only             # Start only MySQL service"
    echo "  $0 --mysql-port 3010        # Start with custom MySQL port"
    echo "  $0 --background             # Start services in background"
    echo "  $0 --stop                   # Stop all running services"
    echo "  $0 --status                 # Show service status"
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        --mysql-port)
            MYSQL_PORT="$2"
            shift 2
            ;;
        --dify-port)
            DIFY_PORT="$2"
            shift 2
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --mysql-only)
            MYSQL_ONLY=true
            shift
            ;;
        --dify-only)
            DIFY_ONLY=true
            shift
            ;;
        --envfile)
            ENVFILE="$2"
            shift 2
            ;;
        --background)
            BACKGROUND=true
            shift
            ;;
        --stop)
            echo "🔴 Stopping MCP services..."
            pkill -f "mcp-mysql" && echo "✓ MySQL service stopped"
            pkill -f "mcp-dify" && echo "✓ Dify service stopped"
            echo "✅ All services stopped"
            exit 0
            ;;
        --status)
            echo "📊 Service Status:"
            echo "==================="
            if pgrep -f "mcp-mysql" > /dev/null; then
                PID=$(pgrep -f "mcp-mysql")
                echo -e "MySQL MCP: ${GREEN}Running${NC} (PID: $PID)"
            else
                echo -e "MySQL MCP: ${RED}Stopped${NC}"
            fi

            if pgrep -f "mcp-dify" > /dev/null; then
                PID=$(pgrep -f "mcp-dify")
                echo -e "Dify MCP:  ${GREEN}Running${NC} (PID: $PID)"
            else
                echo -e "Dify MCP:  ${RED}Stopped${NC}"
            fi
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# 检查Python环境
check_python() {
    if ! command -v python &> /dev/null; then
        if ! command -v python3 &> /dev/null; then
            echo -e "${RED}❌ Python not found${NC}"
            echo "Please install Python 3.7+ to continue"
            exit 1
        else
            PYTHON_CMD="python3"
        fi
    else
        PYTHON_CMD="python"
    fi

    echo -e "${GREEN}✓ Python found: $($PYTHON_CMD --version)${NC}"
}

# 检查项目结构
check_project_structure() {
    echo "🔍 Checking project structure..."

    # 检查main.py文件是否存在
    local main_file="$PROJECT_ROOT/src/server/cli/main.py"
    if [ ! -f "$main_file" ]; then
        echo -e "${RED}❌ Main file not found: $main_file${NC}"

        # 尝试查找main.py文件
        echo "🔍 Searching for main.py files..."
        find "$PROJECT_ROOT" -name "main.py" -type f | head -5
        exit 1
    fi

    # 检查src目录结构
    if [ ! -d "$PROJECT_ROOT/src" ]; then
        echo -e "${RED}❌ src directory not found${NC}"
        exit 1
    fi

    if [ ! -d "$PROJECT_ROOT/src/server" ]; then
        echo -e "${RED}❌ src/server directory not found${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ Project structure looks good${NC}"
}

# 检查依赖
check_dependencies() {
    echo "🔍 Checking dependencies..."

    # 切换到项目根目录进行依赖检查
    cd "$PROJECT_ROOT"

    # 检查必要的Python包
    MISSING_DEPS=()

    $PYTHON_CMD -c "import asyncio" 2>/dev/null || MISSING_DEPS+=("asyncio")
    $PYTHON_CMD -c "import multiprocessing" 2>/dev/null || MISSING_DEPS+=("multiprocessing")

    # 检查可选依赖
    if [ -n "$ENVFILE" ]; then
        $PYTHON_CMD -c "import dotenv" 2>/dev/null || {
            echo -e "${YELLOW}📦 Installing python-dotenv for .env file support...${NC}"
            pip install python-dotenv
        }
    fi

    if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
        echo -e "${RED}❌ Missing dependencies: ${MISSING_DEPS[*]}${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ All dependencies available${NC}"
}

# 检查端口是否被占用
check_port() {
    local port=$1
    local service=$2

    if command -v netstat &> /dev/null; then
        if netstat -tuln | grep -q ":$port "; then
            echo -e "${YELLOW}⚠ Port $port is already in use for $service${NC}"
            return 1
        fi
    elif command -v ss &> /dev/null; then
        if ss -tuln | grep -q ":$port "; then
            echo -e "${YELLOW}⚠ Port $port is already in use for $service${NC}"
            return 1
        fi
    else
        # 如果没有netstat或ss，尝试简单的连接测试
        if timeout 1 bash -c "echo >/dev/tcp/$HOST/$port" 2>/dev/null; then
            echo -e "${YELLOW}⚠ Port $port appears to be in use for $service${NC}"
            return 1
        fi
    fi

    return 0
}

# 构建启动命令
build_command() {
    # 确保从项目根目录运行
    local cmd="cd '$PROJECT_ROOT' && PYTHONPATH='$PROJECT_ROOT:$PYTHONPATH' $PYTHON_CMD -m src.server.cli.main"

    cmd="$cmd --host $HOST"
    cmd="$cmd --mysql-port $MYSQL_PORT"
    cmd="$cmd --dify-port $DIFY_PORT"

    if [ "$MYSQL_ONLY" = true ]; then
        cmd="$cmd --mysql-only"
    fi

    if [ "$DIFY_ONLY" = true ]; then
        cmd="$cmd --dify-only"
    fi

    if [ -n "$ENVFILE" ]; then
        cmd="$cmd --envfile $ENVFILE"
    fi

    echo "$cmd"
}

# 启动服务
start_services() {
    echo "🔧 Starting MCP services..."

    # 检查端口占用
    if [ "$MYSQL_ONLY" != true ] && [ "$DIFY_ONLY" == true ]; then
        # 只启动Dify
        check_port $DIFY_PORT "Dify" || exit 1
    elif [ "$DIFY_ONLY" != true ] && [ "$MYSQL_ONLY" == true ]; then
        # 只启动MySQL
        check_port $MYSQL_PORT "MySQL" || exit 1
    elif [ "$MYSQL_ONLY" != true ] && [ "$DIFY_ONLY" != true ]; then
        # 启动两个服务
        check_port $MYSQL_PORT "MySQL" || exit 1
        check_port $DIFY_PORT "Dify" || exit 1
    fi

    # 构建并执行启动命令
    START_CMD=$(build_command)

    echo "📝 Command: $START_CMD"
    echo ""

    if [ "$BACKGROUND" = true ]; then
        echo "🌅 Starting services in background..."
        # 切换到项目根目录并设置环境变量
        cd "$PROJECT_ROOT"
        export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"
        nohup $PYTHON_CMD -m mcp_for_db.server.cli.main \
            --host $HOST \
            --mysql-port $MYSQL_PORT \
            --dify-port $DIFY_PORT \
            $([ "$MYSQL_ONLY" = true ] && echo "--mysql-only") \
            $([ "$DIFY_ONLY" = true ] && echo "--dify-only") \
            $([ -n "$ENVFILE" ] && echo "--envfile $ENVFILE") \
            > "$SCRIPT_DIR/mcp_services.log" 2>&1 &

        sleep 3

        # 检查服务是否启动成功
        if [ "$MYSQL_ONLY" != true ]; then
            if pgrep -f "mcp-mysql" > /dev/null; then
                echo -e "${GREEN}✓ MySQL MCP started successfully${NC}"
                echo -e "${BLUE}💡 Access at: http://$HOST:$MYSQL_PORT${NC}"
            else
                echo -e "${RED}❌ MySQL MCP failed to start${NC}"
                echo "📄 Check log: tail -f $SCRIPT_DIR/mcp_services.log"
            fi
        fi

        if [ "$DIFY_ONLY" != true ]; then
            if pgrep -f "mcp-dify" > /dev/null; then
                echo -e "${GREEN}✓ Dify MCP started successfully${NC}"
                echo -e "${BLUE}💡 Access at: http://$HOST:$DIFY_PORT${NC}"
            else
                echo -e "${RED}❌ Dify MCP failed to start${NC}"
                echo "📄 Check log: tail -f $SCRIPT_DIR/mcp_services.log"
            fi
        fi

        echo ""
        echo "📋 Use '$0 --status' to check service status"
        echo "🔴 Use '$0 --stop' to stop all services"
        echo "📄 Check '$SCRIPT_DIR/mcp_services.log' for detailed logs"
    else
        echo "🚀 Starting services in foreground..."
        echo "📋 Press Ctrl+C to stop services"
        echo ""

        # 切换到项目根目录并设置环境变量
        cd "$PROJECT_ROOT"
        export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

        exec $PYTHON_CMD -m mcp_for_db.server.cli.main \
            --host $HOST \
            --mysql-port $MYSQL_PORT \
            --dify-port $DIFY_PORT \
            $([ "$MYSQL_ONLY" = true ] && echo "--mysql-only") \
            $([ "$DIFY_ONLY" = true ] && echo "--dify-only") \
            $([ -n "$ENVFILE" ] && echo "--envfile $ENVFILE")
    fi
}

# 主执行流程
main() {
    echo "🚀 MCP Service Launcher"
    echo "======================="

    # 检查环境
    check_python
    check_project_structure
    check_dependencies

    # 显示配置
    echo ""
    echo "📋 Configuration:"
    echo "  Host: $HOST"
    [ "$MYSQL_ONLY" != true ] && echo "  MySQL Port: $MYSQL_PORT"
    [ "$DIFY_ONLY" != true ] && echo "  Dify Port: $DIFY_PORT"
    [ -n "$ENVFILE" ] && echo "  Env File: $ENVFILE"
    [ "$MYSQL_ONLY" = true ] && echo "  Mode: MySQL Only"
    [ "$DIFY_ONLY" = true ] && echo "  Mode: Dify Only"
    [ "$BACKGROUND" = true ] && echo "  Background: Yes"
    echo ""

    # 启动服务
    start_services
}

# 执行主函数
main