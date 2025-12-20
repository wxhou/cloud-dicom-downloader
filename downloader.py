import asyncio
import sys

from yarl import URL

from crawlers import szjudianyun, hinacom, cq12320, shdc, zscloud, ftimage, mtywcloud, yzhcloud, sugh, jdyfy, tdcloud, xa_data



async def main():
	# 支持交互式输入：如果没有提供 URL 参数，则提示用户输入
	if len(sys.argv) > 1 and sys.argv[1].strip():
		url_arg = sys.argv[1]
		extra_args = sys.argv[2:]
	else:
		url_arg = input("请输入要下载的地址 (例如 https://...): ").strip()
		extra_args = []

	host = URL(url_arg).host

	if host.endswith(".medicalimagecloud.com"):
		module_ = hinacom
	elif host == "mdmis.cq12320.cn":
		module_ = cq12320
	elif host == "qr.szjudianyun.com":
		module_ = szjudianyun
	elif host == "ylyyx.shdc.org.cn":
		module_ = shdc
	elif host == "zscloud.zs-hospital.sh.cn":
		module_ = zscloud
	elif host == "app.ftimage.cn" or host == "yyx.ftimage.cn":
		module_ = ftimage
	elif host == "m.yzhcloud.com":
		module_ = yzhcloud
	elif host == "ss.mtywcloud.com":
		module_ = mtywcloud
	elif host == "work.sugh.net":
		module_ = sugh
	elif host == "cloudpacs.jdyfy.com":
		module_ = jdyfy
	elif host == "tdcloudjp.fmmu.edu.cn":
		module_ = tdcloud
	elif host == "yxy.xa-data.cn":
		module_ = xa_data
	else:
		return print("不支持的网站，详情见 README.md")

	await module_.run(url_arg, *extra_args)


if __name__ == "__main__":
	asyncio.run(main())
