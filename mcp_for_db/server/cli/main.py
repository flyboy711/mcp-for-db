import click
import subprocess
import signal
import sys
import time
from datetime import datetime

from mcp_for_db import LOG_LEVEL
from mcp_for_db.server.shared.utils import get_logger, configure_logger

logger = get_logger(__name__)
configure_logger("mcp_server_cli.log")
logger.setLevel(LOG_LEVEL)


@click.command()
@click.option("--mode", default="stdio", type=click.Choice(["stdio", "sse", "streamable_http"]), help="运行模式")
@click.option("--host", default="0.0.0.0", help="主机地址")
@click.option("--mysql_port", type=int, help="MySQL服务端口号")
@click.option("--dify_port", type=int, help="Dify服务端口号")
@click.option("--oauth", is_flag=True, help="启用OAuth认证")
@click.option("--services", multiple=True, type=click.Choice(["mysql", "dify"]),
              help="要启动的服务，可多选（默认启动所有）")
def main(mode, host, mysql_port, dify_port, oauth, services):
    # 如果没有指定服务，则启动所有服务
    if not services:
        services = ["mysql", "dify"]

    processes = []
    python_executable = sys.executable

    logger.info(f"主参数: mode={mode}, host={host}, mysql_port={mysql_port}, dify_port={dify_port}, oauth={oauth}")

    # 启动MySQL服务
    if "mysql" in services:
        mysql_cmd = [
            python_executable, "-m", "mcp_for_db.server.cli.mysql_cli",
            "--mode", mode,
            "--host", host,
        ]
        if mysql_port:
            mysql_cmd.extend(["--port", str(mysql_port)])
        if oauth:
            mysql_cmd.append("--oauth")

        logger.info(f"启动MySQL命令: {' '.join(mysql_cmd)}")
        mysql_process = subprocess.Popen(mysql_cmd)
        processes.append(("MySQL", mysql_process))
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] MySQL服务已启动 (PID: {mysql_process.pid})")

    # 启动 Dify 服务
    if "dify" in services:
        dify_cmd = [
            python_executable, "-m", "mcp_for_db.server.cli.dify_cli",
            "--mode", mode,
            "--host", host
        ]
        if dify_port:
            dify_cmd.extend(["--port", str(dify_port)])
        if oauth:
            dify_cmd.append("--oauth")

        logger.info(f"启动Dify命令: {' '.join(dify_cmd)}")
        dify_process = subprocess.Popen(dify_cmd)
        processes.append(("Dify", dify_process))
        logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Dify服务已启动 (PID: {dify_process.pid})")

    logger.info(f"已启动 {len(processes)} 个服务，模式: {mode}")
    logger.info("按 Ctrl+C 停止所有服务")

    def signal_handler(signum, frame):
        logger.info("\n收到中断信号，正在关闭服务...")
        for service_name, process in processes:
            if process.poll() is None:  # 进程还在运行
                logger.info(f"正在关闭 {service_name}服务 (PID: {process.pid})...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"强制关闭 {service_name}服务...")
                    process.kill()
        sys.exit(0)

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 监控进程状态
        while True:
            time.sleep(2)
            running_count = 0
            for service_name, process in processes:
                if process.poll() is None:
                    running_count += 1
                else:
                    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] {service_name}服务已停止")

            if running_count == 0:
                logger.info("所有服务已停止")
                break
            else:
                pass

    except KeyboardInterrupt:
        logger.info("\n收到中断信号，正在关闭...")
        signal_handler(signal.SIGINT, None)


if __name__ == '__main__':
    main()
