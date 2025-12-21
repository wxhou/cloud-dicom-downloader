"""
统一的日志配置模块
为项目中的所有Python脚本提供结构化日志记录能力
"""
import sys
from pathlib import Path
from loguru import logger
import os

# 确保logs目录存在
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# 移除默认处理器
logger.remove()

# 配置控制台输出 - 只显示INFO级别以上
logger.add(
    sys.stdout,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | <level>{message}</level>",
    colorize=True,
    backtrace=True,
    diagnose=True
)

# 配置文件输出 - 记录所有级别
logger.add(
    logs_dir / "app.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
    rotation="1 day",
    retention="30 days",
    compression="zip",
    encoding="utf-8",
    backtrace=True,
    diagnose=True
)

# 配置错误日志单独文件
logger.add(
    logs_dir / "error.log",
    level="ERROR",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message} | {exception}",
    rotation="1 week",
    retention="90 days",
    compression="zip",
    encoding="utf-8",
    backtrace=True,
    diagnose=True
)

# 配置访问日志（用于网络请求等）
logger.add(
    logs_dir / "access.log",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
    rotation="1 day",
    retention="7 days",
    compression="zip",
    encoding="utf-8"
)

def get_logger(name=None):
    """
    获取配置好的logger实例
    
    Args:
        name (str, optional): logger名称，通常使用__name__
    
    Returns:
        logger: 配置好的loguru logger实例
    """
    if name:
        return logger.bind(name=name)
    return logger

def log_function_entry(func):
    """
    装饰器：记录函数入口和出口
    """
    def wrapper(*args, **kwargs):
        logger.debug(f"进入函数: {func.__name__}")
        try:
            result = func(*args, **kwargs)
            logger.debug(f"函数完成: {func.__name__}")
            return result
        except Exception as e:
            logger.error(f"函数异常: {func.__name__}, 错误: {str(e)}")
            raise
    return wrapper

def log_operation(operation_name):
    """
    装饰器：记录操作执行
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.info(f"开始执行操作: {operation_name}")
            try:
                result = func(*args, **kwargs)
                logger.info(f"操作完成: {operation_name}")
                return result
            except Exception as e:
                logger.error(f"操作失败: {operation_name}, 错误: {str(e)}")
                raise
        return wrapper
    return decorator

# 提供便捷的日志记录函数
def log_request(url, method="GET", status_code=None, response_time=None):
    """记录HTTP请求"""
    if status_code:
        logger.info(f"{method} {url} - {status_code} ({response_time:.3f}s)")
    else:
        logger.debug(f"{method} {url}")

def log_download(file_path, file_size=None):
    """记录文件下载"""
    if file_size:
        logger.info(f"下载文件: {file_path} ({file_size:,} bytes)")
    else:
        logger.info(f"下载文件: {file_path}")

def log_dicom_operation(operation, file_path, success=True, error=None):
    """记录DICOM操作"""
    if success:
        logger.info(f"DICOM操作 - {operation}: {file_path}")
    else:
        logger.error(f"DICOM操作失败 - {operation}: {file_path}, 错误: {error}")

def log_crawler_event(crawler_name, event, details=None):
    """记录爬虫事件"""
    if details:
        logger.info(f"爬虫 {crawler_name} - {event}: {details}")
    else:
        logger.info(f"爬虫 {crawler_name} - {event}")