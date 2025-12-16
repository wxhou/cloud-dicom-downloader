"""
下载 tdcloudjp.fmmu.edu.cn 上面的云影像
"""
import asyncio
import json
import base64
import time
from urllib.parse import urlencode
import re
import sys
from pathlib import Path
from typing import Any

from aiohttp import ClientSession
from playwright.async_api import BrowserContext, Page
from pydicom.datadict import DicomDictionary
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, JPEG2000Lossless
from tqdm import tqdm
from yarl import URL

from crawlers._browser import PlaywrightCrawler, run_with_browser
from crawlers._utils import pathify, new_http_client, parse_dcm_value, SeriesDirectory, suggest_save_dir

_VAR_RE = re.compile(r'var (STUDY_ID|ACCESSION_NUMBER|STUDY_EXAM_UID|LOAD_IMAGE_CACHE_KEY) = "([^"]*)"')


def _get_save_dir(ds):
    return suggest_save_dir(ds["patientName"], ds["studyDescription"], ds["studyDate"])


class TdCloudDownloader:
    """
    TdCloud 医疗影像系统的下载器
    """

    client: ClientSession
    cache_key: str
    dataset: dict[str, Any]

    def __init__(self, client, cache_key, dataset):
        self.client = client
        self.cache_key = cache_key
        self.dataset = dataset
        self.refreshing = asyncio.create_task(self._refresh_cac())

    async def __aenter__(self):
        return self

    def __aexit__(self, *ignore):
        self.refreshing.cancel()
        return self.client.close()

    async def _refresh_cac(self):
        """每分钟要刷新一下 CAC_AUTH 令牌"""
        while True:
            await asyncio.sleep(60)
            (await self.client.get("ImageViewer/renewcacauth")).close()

    async def get_tags(self, info):
        api = "ImageViewer/GetImageDicomTags"
        params = {
            "studyId": info['studyId'],
            "imageId": info['imageId'],
            "frame": "0",
            "storageNodes": self.dataset["storageNode"] or "",
        }
        async with self.client.get(api, params=params) as response:
            return await response.json()

    async def get_image(self, info, raw: bool):
        s, i = info['studyId'], info['imageId'],
        if raw:
            api = f"imageservice/api/image/dicom/{s}/{i}/0/0"
        else:
            api = f"imageservice/api/image/j2k/{s}/{i}/0/3"

        params = {
            "storageNodes": self.dataset["storageNode"] or "",
            "ck": self.cache_key,
        }
        async with self.client.get(api, params=params) as response:
            return await response.read(), response.headers["X-ImageFrame"]

    async def download_all(self, is_raw=False):
        """
        快捷方法，下载全部序列到 DCM 文件，保存的文件名将根据报告自动生成。
        该方法会在控制台显示进度条和相关信息。

        :param is_raw: 是否下载未压缩的图像，默认下载 JPEG2000 格式的。
        """
        save_to = _get_save_dir(self.dataset)
        print(f'保存到: {save_to}')

        for series in self.dataset["displaySets"]:
            name, no, images = pathify(series["description"]) or "Unnamed", series["seriesNumber"], series["images"]
            dir_ = SeriesDirectory(save_to, no, name, len(images))

            tasks = tqdm(images, desc=name, unit="张", file=sys.stdout)
            for i, info in enumerate(tasks):
                # 图片响应头包含的标签不够，必须每个都请求 GetImageDicomTags。
                tags = await self.get_tags(info)

                # 没有标签的视为非 DCM 文件，跳过。
                if len(tags) == 0:
                    continue

                pixels, _ = await self.get_image(info, is_raw)
                _write_dicom(tags, pixels, dir_.get(i, "dcm"))

    @staticmethod
    async def from_url(client: ClientSession, viewer_url: str):
        """
        已经拿到最终查看器页的链接就使用该函数，需要先处理登录并拿到 Cookies。

        :param client: 会话对象，要先拿到相关认证信息
        :param viewer_url: 页面 URL，路径中有 /ImageViewer/StudyView
        """
        async with client.get(viewer_url) as response:
            html4 = await response.text()
            matches = _VAR_RE.findall(html4)
            
            # 提取变量值
            study_id = ""
            accession_number = ""
            exam_uid = ""
            cache_key = ""
            
            for var_name, var_value in matches:
                if var_name == "STUDY_ID":
                    study_id = var_value
                elif var_name == "ACCESSION_NUMBER":
                    accession_number = var_value
                elif var_name == "STUDY_EXAM_UID":
                    exam_uid = var_value
                elif var_name == "LOAD_IMAGE_CACHE_KEY":
                    cache_key = var_value

            # 查看器可能被整合进了其它系统里，路径有前缀。
            origin, path = response.real_url.origin(), response.real_url.path
            if "/ImageViewer/StudyView" in path:
                offset = path.index("/ImageViewer/StudyView")
                client._base_url = origin.with_path(path[:offset + 1])
            else:
                # 如果路径中没有找到 /ImageViewer/StudyView，则使用默认的 origin
                client._base_url = origin

        # 获取检查的基本信息，顺便也判断下访问是否成功。
        params = {
            "studyId": study_id,
            "accessionNumber": accession_number,
            "examuid": exam_uid,
            "minThickness": "5"
        }
        async with client.get("ImageViewer/GetImageSet", params=params) as response:
            image_set = await response.json()

        return TdCloudDownloader(client, cache_key, image_set)


class TdCloudPlaywrightCrawler(PlaywrightCrawler):
    """使用 Playwright 处理需要人工输入验证码的页面"""

    def __init__(self, report_url: str):
        self.report_url = report_url
        self.result = None

    async def _do_run(self, context: BrowserContext):
        page = await context.new_page()

        print("正在打开页面...")
        await page.goto(self.report_url)

        print("请在浏览器中输入验证码并点击“查看影像”，脚本将等待新标签页打开并自动继续...")

        # 用户在完成验证码并点击“查看影像”后，系统会在新标签页打开查看器。
        # 这里等待新标签页出现，然后在新标签页中轮询 LOAD_IMAGE_CACHE_KEY。
        new_page: Page | None = None
        cache_key = ""
        max_wait = 600  # seconds (延长到 10 分钟)
        interval = 1.0  # 轮询间隔改为 1 秒，减少频繁 evaluate
        waited = 0.0
        try:
            print("等待新标签页打开（尝试自动点击页面上的“查看影像”，如果不存在则等待用户手动打开）...")
            try:
                # 优先尝试自动点击页面上的“查看影像”元素并捕获弹出页
                try:
                    el = await page.wait_for_selector('text="查看影像"', timeout=30000)
                    print('检测到页面上的“查看影像”元素，尝试点击以打开新标签页...')
                    async with page.expect_popup() as popup_info:
                        await el.click()
                    new_page = await popup_info.value
                    print('已通过自动点击打开新标签页')
                except Exception:
                    # 如果页面没有该元素或点击失败，则等待用户手动打开新标签页
                    print('未找到自动点击目标，转为等待用户手动打开新标签页（popup）')
                    new_page = await page.wait_for_event("popup", timeout=int(max_wait * 1000))
            except Exception:
                print("超时：未检测到新标签页。请确认已在浏览器中点击“查看影像”。")
                return

            # 等待新标签页完成初始加载
            print(f"新标签页已打开，URL: {new_page.url}")
            await new_page.wait_for_load_state("domcontentloaded")

            # 回退检测：尝试直接从页面 HTML 中提取 JS 变量（避免依赖全局变量存在时机）
            try:
                html = await new_page.content()
                html_matches = _VAR_RE.findall(html)
                if html_matches:
                    print(f"从页面 HTML 中提取到 {len(html_matches)} 个变量声明，尝试解析")
                    for var_name, var_value in html_matches:
                        if var_name == "STUDY_ID" and not study_id:
                            study_id = var_value
                        elif var_name == "ACCESSION_NUMBER" and not accession_number:
                            accession_number = var_value
                        elif var_name == "STUDY_EXAM_UID" and not exam_uid:
                            exam_uid = var_value
                        elif var_name == "LOAD_IMAGE_CACHE_KEY" and not cache_key:
                            cache_key = var_value
                    if cache_key:
                        print("已从 HTML 中获取到 LOAD_IMAGE_CACHE_KEY，跳过轮询")
            except Exception as e:
                print(f"尝试从页面 HTML 提取变量时出错: {e}")

            # 在新标签页中轮询 JS 变量，尽量容忍导航导致的 ExecutionContext 被销毁。
            last_log = time.time()
            while waited < max_wait:
                try:
                    cache_key = await new_page.evaluate("typeof LOAD_IMAGE_CACHE_KEY !== 'undefined' ? LOAD_IMAGE_CACHE_KEY : ''")
                    if cache_key:
                        break
                except Exception:
                    # 可能在导航过程中执行上下文被销毁，忽略并重试
                    pass
                await asyncio.sleep(interval)
                waited += interval
                # 每隔 5 秒输出一次轮询进度
                if time.time() - last_log >= 5:
                    print(f"等待 LOAD_IMAGE_CACHE_KEY 中... 已等待 {int(waited)}s")
                    last_log = time.time()

            if not cache_key:
                print("超时：未检测到新标签页中的 LOAD_IMAGE_CACHE_KEY。请确认已在查看器中完成操作。")
                return
        except Exception as e:
            print(f"在等待新标签页或检测变量时出错: {e}")
            return

        try:
            # 从新标签页中提取必要的 JavaScript 变量（此时应已存在）
            page_for_eval = new_page or page
            study_id = await page_for_eval.evaluate("typeof STUDY_ID !== 'undefined' ? STUDY_ID : ''")
            accession_number = await page_for_eval.evaluate("typeof ACCESSION_NUMBER !== 'undefined' ? ACCESSION_NUMBER : ''")
            exam_uid = await page_for_eval.evaluate("typeof STUDY_EXAM_UID !== 'undefined' ? STUDY_EXAM_UID : ''")
            cache_key = cache_key or await page_for_eval.evaluate("typeof LOAD_IMAGE_CACHE_KEY !== 'undefined' ? LOAD_IMAGE_CACHE_KEY : ''")

            print(f"提取到 Study ID: {study_id}")
            print(f"提取到 Accession Number: {accession_number}")

            # 使用新标签页的 URL 推断更准确的 base_url（可能包含前缀）
            page_url = page_for_eval.url
            url_obj = URL(page_url)
            path = url_obj.path
            origin = url_obj.origin()
            if "/ImageViewer/StudyView" in path:
                offset = path.index("/ImageViewer/StudyView")
                base_url = origin.with_path(path[:offset + 1])
            else:
                base_url = origin

            # 创建 HTTP 客户端并设置 base_url，同时将浏览器的 cookies 注入到客户端
            client = new_http_client()
            client._base_url = base_url

            try:
                # 将 Playwright 上下文的 cookies 同步到 aiohttp 的 cookie_jar
                browser_cookies = await context.cookies()
                print(f"同步浏览器 cookies 到 aiohttp: 共 {len(browser_cookies)} 个")
                synced = 0
                for c in browser_cookies:
                    # response_url 用于确定 cookie 的作用域
                    try:
                        client.cookie_jar.update_cookies({c['name']: c['value']}, response_url=str(origin))
                        synced += 1
                    except Exception:
                        # 保守回退：忽略无法设置的 cookie
                        pass
                print(f"已尝试设置 cookie: 成功 {synced}")
            except Exception as e:
                print(f"同步 cookies 时发生异常: {e}")

            # 记录发向 GetImageSet 的请求用于诊断
            found_request_url = None
            def _on_request(req):
                nonlocal found_request_url
                try:
                    u = req.url
                    # 记录第一个 GetImageSet 请求
                    if '/ImageViewer/GetImageSet' in u and not found_request_url:
                        found_request_url = u
                        print(f"捕获到页面发出的 GetImageSet 请求: {found_request_url}")
                    # 额外打印关键请求以便追踪
                    if '/ImageViewer/GetImageDicomTags' in u or '/imageservice/api/image' in u:
                        print(f"页面将发起请求: {u}")
                except Exception:
                    pass

            page_for_eval.on('request', _on_request)

            # 获取检查的基本信息
            params = {
                "studyId": study_id,
                "accessionNumber": accession_number,
                "examuid": exam_uid,
                "minThickness": "5"
            }

            image_set = None
            image_set = None
            try:
                async with client.get("ImageViewer/GetImageSet", params=params) as response:
                    image_set = await response.json()
            except Exception:
                if found_request_url:
                    print(f"浏览器实际发起的 GetImageSet URL: {found_request_url}")
                # 在页面上下文使用 fetch 获取 image_set，使用浏览器的认证上下文
                try:
                    fetch_url = str(base_url.with_path('ImageViewer/GetImageSet')) + '?' + urlencode(params)
                    image_set = await page_for_eval.evaluate(
                        "async (url) => { const r = await fetch(url, {credentials: 'same-origin'}); if(!r.ok) throw new Error('fetch failed ' + r.status); return r.json(); }",
                        fetch_url,
                    )
                except Exception as ee:
                    print(f"在页面内使用 fetch 获取 image_set 失败: {ee}")
                    raise

            # 使用浏览器上下文完成后续所有请求（GetImageDicomTags / image 服务），确保使用相同的认证态
            async def browser_fetch_json(path: str, params: dict):
                url = str(base_url.with_path(path)) + '?' + urlencode(params)
                return await page_for_eval.evaluate(
                    "async (url) => { const r = await fetch(url, {credentials: 'same-origin'}); if(!r.ok) throw new Error('fetch failed ' + r.status); return r.json(); }",
                    url,
                )

            async def browser_fetch_image(path: str, params: dict):
                url = str(base_url.with_path(path)) + '?' + urlencode(params)
                # 返回 base64 编码的图像和 X-ImageFrame 头
                return await page_for_eval.evaluate(
                    "async (url) => { const r = await fetch(url, {credentials: 'same-origin'}); if(!r.ok) throw new Error('fetch failed ' + r.status); const buf = await r.arrayBuffer(); const bytes = new Uint8Array(buf); let binary = ''; const chunk = 0x8000; for(let i=0;i<bytes.length;i+=chunk){ binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i,i+chunk))); } const b64 = btoa(binary); return {b64: b64, frame: r.headers.get('X-ImageFrame')}; }",
                    url,
                )

            # 下载逻辑（基于 image_set 内容）
            save_to = _get_save_dir(image_set)
            print(f'保存到: {save_to}')

            for series in image_set.get("displaySets", []):
                name, no, images = pathify(series.get("description") or "" ) or "Unnamed", series.get("seriesNumber"), series.get("images", [])
                dir_ = SeriesDirectory(save_to, no, name, len(images))

                tasks = tqdm(images, desc=name, unit="张", file=sys.stdout)
                for i, info in enumerate(tasks):
                    tags = await browser_fetch_json('ImageViewer/GetImageDicomTags', {
                        'studyId': info['studyId'],
                        'imageId': info['imageId'],
                        'frame': '0',
                        'storageNodes': image_set.get('storageNode') or ''
                    })

                    if not tags:
                        continue

                    # 优先下载 j2k（压缩），若 is_raw 需要可改
                    img_resp = await browser_fetch_image(f'imageservice/api/image/j2k/{info["studyId"]}/{info["imageId"]}/0/3', {'storageNodes': image_set.get('storageNode') or '', 'ck': cache_key})
                    img_bytes = base64.b64decode(img_resp['b64'])
                    _write_dicom(tags, img_bytes, dir_.get(i, 'dcm'))

            # 下载完成后，保持新标签页打开，直到用户手动关闭页面为止。
            try:
                keep_page = new_page or page
                print("下载完成。浏览器页面将保持打开，关闭页面以结束程序。")
                await keep_page.wait_for_close()
            except Exception:
                # 如果页面已经被关闭，直接返回
                pass
        except Exception as e:
            print(f"下载过程中出现错误: {e}")
        finally:
            await client.close()


def _write_dicom(tag_list: list, image: bytes, filename: Path):
    ds = Dataset()
    ds.file_meta = FileMetaDataset()

    # GetImageDicomTags 的响应不含 VR，故私有标签只能假设为 LO 类型。
    for item in tag_list:
        tag = Tag(item["tag"].split(",", 2))
        definition = DicomDictionary.get(tag)
 
        if tag.group == 2:
            # 0002 的标签只能放在 file_meta 里而不能在 ds 中存在。
            if definition:
                vr, key = definition[0], definition[4]
                value = parse_dcm_value(item["value"], vr)
                setattr(ds.file_meta, key, value)
        elif definition:
            vr, key = definition[0], definition[4]
            setattr(ds, key, parse_dcm_value(item["value"], vr))
        else:
            # 正好 PrivateCreator 出现在它的标签之前，按顺序添加即可。
            # DataElement 对 LO 类型会自动按斜杠分割多值字符串。
            ds.add_new(tag, "LO", item["value"])

    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID

    # 根据文件体积和头部自动判断类型。
    px_size = (ds.BitsAllocated + 7) // 8 * ds.Rows * ds.Columns
    if image[16:23] == b"ftypjp2" and len(image) != px_size:
        ds.PixelData = encapsulate([image])
        ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    else:
        ds.PixelData = image
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds.save_as(filename, enforce_file_format=True)


async def run(url_str, *args):
    print(f"下载TdCloud DICOM")

    # 使用 Playwright 处理需要人工输入验证码的页面
    crawler = TdCloudPlaywrightCrawler(url_str)
    await run_with_browser(crawler)