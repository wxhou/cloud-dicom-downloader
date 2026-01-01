import asyncio
import sys

from yarl import URL

from crawlers import szjudianyun, hinacom, cq12320, shdc, zscloud, ftimage, mtywcloud, yzhcloud, sugh, jdyfy, tdcloud, xa_data
from tools.logging_config import get_logger

logger = get_logger(__name__)


async def main():
	logger.info("开始执行DICOM影像下载任务")
	
	# 支持交互式输入：如果没有提供 URL 参数，则提示用户输入
	if len(sys.argv) > 1 and sys.argv[1].strip():
		url_arg = sys.argv[1]
		extra_args = sys.argv[2:]
		logger.info(f"使用命令行参数: {url_arg}, 额外参数: {extra_args}")
	else:
		url_arg = input("请输入要下载的地址 (例如 https://...): ").strip()
		extra_args = []
		logger.info("使用交互式输入模式")

	try:
		parsed_url = URL(url_arg)
		host = parsed_url.host
		if not host:
			error_msg = f"无法解析URL中的主机名: {url_arg}"
			logger.error(error_msg)
			return print(error_msg)
	except Exception as e:
		error_msg = f"URL格式错误: {url_arg}, 错误: {str(e)}"
		logger.error(error_msg)
		return print(error_msg)
	
	logger.info(f"解析到目标主机: {host}")

	if host.endswith(".medicalimagecloud.com"):
		module_ = hinacom
		logger.info("选择海纳康医学影像云下载器模块")
	elif host == "mdmis.cq12320.cn":
		module_ = cq12320
		logger.info("选择重庆12320下载器模块")
	elif host == "qr.szjudianyun.com":
		module_ = szjudianyun
		logger.info("选择深圳聚点云下载器模块")
	elif host == "ylyyx.shdc.org.cn":
		module_ = shdc
		logger.info("选择上海医学影像中心下载器模块")
	elif host == "zscloud.zs-hospital.sh.cn":
		module_ = zscloud
		logger.info("选择中山医院下载器模块")
	elif host == "app.ftimage.cn" or host == "yyx.ftimage.cn":
		module_ = ftimage
		logger.info("选择飞图影像下载器模块")
	elif host == "m.yzhcloud.com":
		module_ = yzhcloud
		logger.info("选择远程影像云下载器模块")
	elif host == "ss.mtywcloud.com":
		module_ = mtywcloud
		logger.info("选择万网云下载器模块")
	elif host == "work.sugh.net":
		module_ = sugh
		logger.info("选择上航院下载器模块")
	elif host == "cloudpacs.jdyfy.com":
		module_ = jdyfy
		logger.info("选择金蝶医疗云下载器模块")
	elif host == "tdcloudjp.fmmu.edu.cn":
		module_ = tdcloud
		logger.info("选择第四军医大学云下载器模块")
	elif host == "yxy.xa-data.cn":
		module_ = xa_data
		logger.info("选择西安数据下载器模块")
	else:
		error_msg = f"不支持的网站: {host}, 详情见 README.md"
		logger.error(error_msg)
		return print(error_msg)

	try:
		logger.info(f"开始执行下载器模块: {module_.__name__}")
		await module_.run(url_arg, *extra_args)
		logger.info("下载器任务执行完成")
	except Exception as e:
		logger.error(f"下载器模块执行失败: {str(e)}", exc_info=True)
		raise


if __name__ == "__main__":
	try:
		logger.info("启动DICOM影像下载器")
		asyncio.run(main())
		logger.info("下载器正常退出")
	except KeyboardInterrupt:
		logger.info("用户中断操作")
	except Exception as e:
		logger.error(f"程序异常退出: {str(e)}", exc_info=True)
		sys.exit(1)
