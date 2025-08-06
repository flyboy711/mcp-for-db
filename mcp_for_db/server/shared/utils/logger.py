import os
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


def configure_logger(log_filename="app.logs"):
    """配置日志系统

    Args:
        log_filename (str): 日志文件名
    """
    # 获取项目根目录
    root_dir = Path(__file__).parent.parent.parent.parent.parent
    os.makedirs(os.path.join(root_dir, "datas", "logs"), exist_ok=True)
    log_path = os.path.join(os.path.join(root_dir, "datas", "logs"), log_filename)

    # 设置日志格式
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
    formatter = logging.Formatter(log_format)

    # 创建根日志记录器
    logger = logging.getLogger()

    # 清除所有已有处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 创建并添加文件处理器（按天轮转，保留7天）
    file_handler = TimedRotatingFileHandler(
        log_path,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 创建并添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 设置其他库的日志级别
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name=None):
    """获取日志记录器实例"""
    return logging.getLogger(name)


if __name__ == "__main__":
    pass
    # # 获取项目根目录
    # root_dir = Path(__file__).parent.parent.parent.parent.parent
    #
    # os.makedirs(os.path.join(root_dir, "logs"), exist_ok=True)
    # log_path = os.path.join(os.path.join(root_dir, "logs"), "log_filename.log")
    #
    # print(root_dir)
