import argparse
import os
import signal
import sys
import threading
import time
from typing import Dict, Optional
import multiprocessing as mp

from mcp_for_db.server.core import ServiceManager
from mcp_for_db.server.shared.utils import configure_logger, get_logger

running_processes: Dict[str, mp.Process] = {}
shutdown_event = threading.Event()

logger = get_logger(__name__)


def create_parser():
    """创建简化的命令行解析器"""
    parser = argparse.ArgumentParser(description="Simple MCP Service Manager")

    parser.add_argument('--mysql-port', type=int, default=3000, help='MySQL service port (default: 3000)')
    parser.add_argument('--dify-port', type=int, default=3001, help='Dify service port (default: 3001)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind (default: 0.0.0.0)')
    parser.add_argument('--envfile', help='Custom environment file path')
    parser.add_argument('--mysql-only', action='store_true', help='Start only MySQL service')
    parser.add_argument('--dify-only', action='store_true', help='Start only Dify service')

    return parser


def setup_signal_handlers():
    """设置信号处理器用于优雅关闭"""

    def signal_handler(signum, frame):
        print(f"\n Received signal {signum}, shutting down services...")
        shutdown_event.set()
        stop_all_services()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def load_custom_env(envfile: str):
    """加载自定义环境文件"""
    if envfile and os.path.exists(envfile):
        try:
            from dotenv import load_dotenv
            load_dotenv(envfile)
            print(f"Loaded environment file: {envfile}")
        except ImportError:
            print("Warning: python-dotenv not installed, skipping env file")
    elif envfile:
        print(f"Warning: Environment file not found: {envfile}")


def run_service_process(service_name: str, host: str, port: int, envfile: Optional[str] = None):
    """在单独进程中运行服务"""
    try:
        # 在子进程中重新配置日志
        configure_logger(log_filename=f"{service_name}_service.log")

        # 加载环境文件
        if envfile:
            load_custom_env(envfile)

        # 创建服务管理器和服务实例
        service_manager = ServiceManager()
        service = service_manager.create_service(service_name)

        print(f"🚀 [{service_name}] Starting on {host}:{port}")

        # 使用streamable_http模式运行服务
        service.run_streamable_http(host, port, oauth=False)

    except Exception as e:
        print(f"❌ [{service_name}] Failed to start: {e}")
        logger.exception(f"Service {service_name} failed")


def start_services(host: str, mysql_port: int, dify_port: int, envfile: Optional[str] = None,
                   mysql_only: bool = False, dify_only: bool = False):
    """启动MCP服务"""
    global running_processes

    services_to_start = []

    if not dify_only:
        services_to_start.append(('mysql', mysql_port))

    if not mysql_only:
        services_to_start.append(('dify', dify_port))

    if not services_to_start:
        print("⚠ No services to start")
        return

    print(f"🚀 Starting {len(services_to_start)} MCP services...")

    # 启动服务进程
    for service_name, port in services_to_start:
        process = mp.Process(
            target=run_service_process,
            args=(service_name, host, port, envfile),
            name=f"mcp-{service_name}"
        )
        process.start()
        running_processes[service_name] = process
        print(f"✓ [{service_name}] Started (PID: {process.pid}) on {host}:{port}")

    print(f"🎉 Successfully started {len(services_to_start)} services")


def stop_all_services():
    """停止所有运行中的服务"""
    global running_processes

    if not running_processes:
        return

    print("🔴 Stopping all services...")

    # 停止所有进程
    for service_name, process in running_processes.items():
        try:
            if process.is_alive():
                print(f"🔴 Stopping {service_name} (PID: {process.pid})...")
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    print(f"⚡ Force killing {service_name}...")
                    process.kill()
                    process.join()
                print(f"✓ {service_name} stopped")
        except Exception as e:
            print(f"❌ Error stopping {service_name}: {e}")

    running_processes.clear()
    print("✓ All services stopped")


def show_service_status():
    """显示服务状态"""
    print("\n📊 Service Status:")
    print("-" * 50)

    if running_processes:
        print("🔧 Running Services:")
        for service_name, process in running_processes.items():
            status = "🟢 Running" if process.is_alive() else "🔴 Stopped"
            pid = process.pid if process.is_alive() else "N/A"
            print(f"  {service_name:<15} {status:<12} PID: {pid}")
    else:
        print("  No services running")


def monitor_services():
    """监控服务状态"""
    global running_processes

    while not shutdown_event.is_set():
        # 检查已停止的进程
        dead_processes = []
        for service_name, process in running_processes.items():
            if not process.is_alive():
                dead_processes.append(service_name)
                print(f"🔴 Service {service_name} has stopped unexpectedly")

        # 清理已停止的进程
        for service_name in dead_processes:
            del running_processes[service_name]

        # 如果所有服务都停止了，退出监控
        if not running_processes:
            print("🔴 All services have stopped")
            shutdown_event.set()
            break

        time.sleep(5)  # 每5秒检查一次


def main():
    """主入口函数"""
    parser = create_parser()
    args = parser.parse_args()

    # 配置日志
    configure_logger(log_filename="mcp_services.log")

    # 设置信号处理器
    setup_signal_handlers()

    # 加载环境文件
    if args.envfile:
        load_custom_env(args.envfile)

    print("🚀 Simple MCP Service Manager")
    print("=" * 50)

    try:
        # 启动服务
        start_services(
            host=args.host,
            mysql_port=args.mysql_port,
            dify_port=args.dify_port,
            envfile=args.envfile,
            mysql_only=args.mysql_only,
            dify_only=args.dify_only
        )

        if not running_processes:
            print("❌ No services were started")
            return

        # 显示初始状态
        show_service_status()

        # 启动监控线程
        monitor_thread = threading.Thread(target=monitor_services, daemon=True)
        monitor_thread.start()

        print("\n📡 Services are running. Press Ctrl+C to stop.")
        print("💡 Access services at:")
        if not args.dify_only:
            print(f"   • MySQL MCP: http://{args.host}:{args.mysql_port}")
        if not args.mysql_only:
            print(f"   • Dify MCP:  http://{args.host}:{args.dify_port}")

        # 等待用户中断或所有服务停止
        try:
            while not shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🔴 Received exit signal...")

    except Exception as e:
        print(f"❌ Error: {e}")
        logger.exception("Main execution failed")
    finally:
        # 确保清理所有资源
        stop_all_services()


def stdio_entry():
    """控制台脚本入口"""
    main()


if __name__ == "__main__":
    main()
