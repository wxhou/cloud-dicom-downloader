import asyncio
import sys
from typing import Any, Optional

from playwright.async_api import Frame, Page, ElementHandle, Playwright, Browser, Error, BrowserContext, WebSocket, \
	Response, async_playwright
from tools.logging_config import get_logger

logger = get_logger(__name__)

_driver_instance: Any = None
_playwright: Playwright
_browser: Browser


async def launch_browser(playwright: Playwright) -> Browser:
	"""
	考虑到 Playwright 的支持成熟度，还是尽可能地选择 chromium 系浏览器。
	"""
	logger.info("启动浏览器实例")
	try:
		browser = await playwright.chromium.launch(headless=False)
		logger.info("成功启动Chromium浏览器")
		return browser
	except Error as e:
		if not e.message.startswith("BrowserType.launch: Executable doesn't exist"):
			logger.error(f"启动浏览器失败: {str(e)}")
			raise

	if sys.platform == "win32":
		logger.info("使用Windows自带的Edge浏览器")
		return await playwright.chromium.launch(headless=False,
			executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

	logger.error("在该系统上运行必须提供浏览器的路径")
	raise Exception("在该系统上运行必须提供浏览器的路径。")


async def wait_text(context: Page | Frame | ElementHandle, selector: str) -> Optional[str]:
	"""
	等待匹配指定选择器的元素出现，并读取其 textContent 属性。
	最好使用 wait_for_selector 而不是 query_selector，以确保元素已插入。

	:param context: 搜索范围，可以是页面或某个元素。
	:param selector: CSS 选择器
	"""
	logger.debug(f"等待元素出现: {selector}")
	try:
		element = await context.wait_for_selector(selector)
		text_content = await element.text_content()
		if text_content:
			logger.debug(f"成功获取元素文本: {text_content[:50]}...")
		else:
			logger.debug("元素文本为空")
		return text_content
	except Exception as e:
		logger.error(f"等待元素失败: {selector}, 错误: {str(e)}")
		raise


class PlaywrightCrawler:
	"""本项目的爬虫都比较简单，有固定的模式，所以写个抽象类来统一下代码"""

	_autoclose_waiter = asyncio.Event()
	_context: Optional[BrowserContext] = None

	def _prepare_page(self, page: Page):
		page.on("websocket", self._on_websocket)
		page.on("close", self._check_all_closed)

	# 关闭窗口并不结束浏览器进程，只能依靠页面计数来判断。
	# https://github.com/microsoft/playwright/issues/2946
	def _check_all_closed(self, _):
		if len(self._context.pages) == 0:
			logger.debug("所有页面已关闭，触发自动清理事件")
			self._autoclose_waiter.set()

	def _on_response(self, response: Response):
		if not response.ok:
			logger.warning(f"HTTP响应异常: {response.status} {response.url}")

	def _on_websocket(self, ws: WebSocket):
		logger.debug(f"WebSocket连接: {ws.url}")

	async def _do_run(self, context: BrowserContext):
		pass

	async def run(self, context: BrowserContext):
		logger.info("启动爬虫执行")
		self._context = context
		context.on("page", self._prepare_page)
		context.on("response", self._on_response)
		try:
			return await self._do_run(context)
		finally:
			logger.info("爬虫执行完成")


async def run_with_browser(crawler: PlaywrightCrawler, **kwargs):
	"""
	启动 Playwright 浏览器的快捷函数，单个 Browser 实例创建新的 Context。

	因为这库有四层（ContextManager，Playwright，Browser，BrowserContext）
	每次启动都要嵌套好几个 with 很烦，所以搞了一个全局的实例并支持自动销毁。

	:param crawler:
	:param kwargs: 转发到 Browser.new_context() 的参数
	"""
	global _browser, _playwright, _driver_instance

	logger.info(f"使用浏览器执行爬虫: {crawler.__class__.__name__}")
	
	if not _driver_instance:
		logger.info("初始化Playwright实例")
		_driver_instance = async_playwright()
		_playwright = await _driver_instance.__aenter__()
		_browser = await launch_browser(_playwright)

	try:
		logger.info("创建新的浏览器上下文")
		async with await _browser.new_context(**kwargs) as context:
			return await crawler.run(context)
	finally:
		if len(_browser.contexts) == 0:
			logger.info("关闭浏览器实例")
			await _browser.close()
			await _driver_instance.__aexit__()
		else:
			logger.debug(f"浏览器仍有{len(_browser.contexts)}个上下文在使用中")
