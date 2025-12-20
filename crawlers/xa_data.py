"""
专门为 yxy.xa-data.cn（xa-data）实现的爬虫。

该站点的查看器和 tdcloud 类似但布局不同，故实现一个更鲁棒的 Playwright 爬虫：
- 打开初始页面，尝试自动点击查看影像按钮或等待用户手动操作
- 监听页面发出的 XHR 请求以捕获 GetImageSet / LoadImageCacheKey
- 在新标签页中提取所需变量（studyId/accession/examuid/LOAD_IMAGE_CACHE_KEY）
- 将浏览器认证上下文（cookies）注入 aiohttp 客户端，然后按 tdcloud 的方式下载图片

实现尽量复用 tdcloud 的请求/写入逻辑（适配性更强）。
"""
import asyncio
import time
import json
from urllib.parse import urlencode
from typing import Any

from aiohttp import ClientSession
from yarl import URL

from crawlers._browser import PlaywrightCrawler, run_with_browser
from crawlers._utils import new_http_client, pathify, SeriesDirectory, suggest_save_dir, parse_dcm_value
from crawlers import tdcloud
from crawlers.xa_helpers import normalize_images_field, fetch_image_bytes, build_minimal_tags


class XaDataPlaywrightCrawler(PlaywrightCrawler):
    def __init__(self, report_url: str):
        self.report_url = report_url

    async def _do_run(self, context):
        page = await context.new_page()
        # 先通过 CDP 在导航前开启触摸/设备仿真，确保页面首次加载时就识别移动环境
        try:
            cdp = await context.new_cdp_session(page)
            await cdp.send('Emulation.setDeviceMetricsOverride', {
                'width': 393, 'height': 852, 'deviceScaleFactor': 3, 'mobile': True
            })
            await cdp.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
            await cdp.send('Emulation.setEmitTouchEventsForMouse', {'enabled': True, 'configuration': 'mobile'})
            print('已在导航前通过 CDP 应用触摸/设备仿真')
        except Exception as e:
            print('导航前应用 CDP 仿真失败:', e)

        print("正在打开 xa-data 页面...")
        await page.goto(self.report_url)

        print("如果页面需要验证码或交互，请在浏览器中完成；脚本将在新标签页打开后继续。")

        new_page = None
        found_request_url = None
        study_id = ""
        accession_number = ""
        exam_uid = ""

        # 监听页面请求，尝试抓取 GetImageSet、/nwservice/rispacsresp 或相关请求
        def _on_request(req):
            nonlocal found_request_url
            try:
                u = req.url
                if '/ImageViewer/GetImageSet' in u and not found_request_url:
                    found_request_url = u
                # 站点会通过 /nwservice/rispacsresp 返回 study/series/images json
                if '/nwservice/rispacsresp' in u and not found_request_url:
                    found_request_url = u
                if '/ImageViewer/GetImageDicomTags' in u or '/imageservice/api/image' in u:
                    print(f"页面将发起请求: {u}")
            except Exception:
                pass

        page.on('request', _on_request)

        # 尝试自动点击可能存在的查看按钮
        try:
            for sel_text in ["查看影像", "查看", "查看影像/查看", "查看影像/查看影像"]:
                try:
                    el = await page.query_selector(f'text="{sel_text}"')
                    if el:
                        try:
                            async with page.expect_popup() as popup_info:
                                await el.click()
                            new_page = await popup_info.value
                            break
                        except Exception:
                            # 点击未产生 popup，则继续
                            pass
                except Exception:
                    pass

            if not new_page:
                # 有些站点在当前页面发起请求并不弹出新窗口，等待 popup 或关键请求 / URL 变化
                wait_timeout = 30
                poll_interval = 0.5
                waited = 0.0
                while waited < wait_timeout and not new_page and not found_request_url:
                    # 检查是否有新页面被打开
                    if len(context.pages) > 1:
                        # 取最新页面
                        new_page = context.pages[-1]
                        break
                    # 检查当前页面 URL 是否已跳转到 viewer 路径
                    try:
                        cur = page.url
                        if '/ImageViewer' in cur or '/viewer' in cur or '/nwservice' in cur:
                            found_request_url = found_request_url or cur
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(poll_interval)
                    waited += poll_interval

                if not new_page and not found_request_url:
                    # 扩展等待（最多 30 秒），以便用户人工交互完成
                    print('未自动打开新标签页或检测到关键请求，继续等待用户手动打开（最多 30 秒）')
                    try:
                        new_page = await page.wait_for_event('popup', timeout=30000)
                    except Exception:
                        if not found_request_url:
                            print('超时：未检测到新标签页或关键请求')
                            return
        except Exception as e:
            print(f"在尝试打开查看器时发生错误: {e}")
            return

        page_for_eval = new_page or page
        await page_for_eval.wait_for_load_state('domcontentloaded')

        # 已在导航前通过 CDP 应用触摸/设备仿真（如有必要）

        # 监听新页面的请求也以便捕获 GetImageSet
        page_for_eval.on('request', _on_request)

        # 不再使用 tdcloud 风格的 LOAD_IMAGE_CACHE_KEY，改为依赖捕获到的请求或页面变量

        try:
            study_id = await page_for_eval.evaluate("typeof STUDY_ID !== 'undefined' ? STUDY_ID : ''")
            accession_number = await page_for_eval.evaluate("typeof ACCESSION_NUMBER !== 'undefined' ? ACCESSION_NUMBER : ''")
            exam_uid = await page_for_eval.evaluate("typeof STUDY_EXAM_UID !== 'undefined' ? STUDY_EXAM_UID : ''")
        except Exception:
            # 忽略评估错误，后面会用请求抓取
            pass

        # 构造 base_url
        page_url = page_for_eval.url
        url_obj = URL(page_url)
        path = url_obj.path
        origin = url_obj.origin()
        if "/ImageViewer/StudyView" in path:
            offset = path.index("/ImageViewer/StudyView")
            base_url = origin.with_path(path[:offset + 1])
        else:
            base_url = origin

        # 创建 HTTP 客户端并注入 cookies
        client = new_http_client()
        client._base_url = base_url

        try:
            browser_cookies = await context.cookies()
            for c in browser_cookies:
                try:
                    name = c.get('name') if isinstance(c, dict) else None
                    value = c.get('value') if isinstance(c, dict) else None
                    if name and value:
                        client.cookie_jar.update_cookies({name: value}, response_url=origin)
                except Exception:
                    pass
        except Exception:
            pass

        # 如果页面没有提供必要变量，通过 page 的 fetch 或者捕获到的请求 URL 来获取 image_set
        params = None
        if study_id or accession_number or exam_uid:
            params = {
                'studyId': study_id,
                'accessionNumber': accession_number,
                'examuid': exam_uid,
                'minThickness': '5'
            }

        image_set = None
        if params:
            try:
                async with client.get('ImageViewer/GetImageSet', params=params) as resp:
                    image_set = await resp.json()
            except Exception:
                image_set = None

        if image_set is None and found_request_url:
            # 若能捕获浏览器真正发出的 GetImageSet URL，则在页面上下文通过 fetch 获取
            try:
                image_set = await page_for_eval.evaluate(
                    "async (url) => { const r = await fetch(url, {credentials: 'same-origin'}); if(!r.ok) throw new Error('fetch failed '+r.status); return r.json(); }",
                    found_request_url,
                )
            except Exception:
                image_set = None

        if image_set is None:
            # 最后尝试让 tdcloud 的通用解析去处理（如果结构兼容）
            print('未直接获取到 image_set，尝试使用 tdcloud 的通用解析作为回退')
            await tdcloud.run(self.report_url)
            await client.close()
            return

        # 调试输出：打印发现的请求 URL 和 image_set 概览，便于定位未写入文件的原因
        try:
            print('found_request_url:', found_request_url)
            print('image_set keys:', list(image_set.keys()) if isinstance(image_set, dict) else type(image_set))
            if isinstance(image_set, dict):
                ds = image_set.get('displaySets') or image_set.get('display_sets') or []
                print('displaySets length:', len(ds))
                if len(ds) > 0:
                    # 打印第一个 display set 的摘要
                    first = ds[0]
                    try:
                        print('first display set sample keys:', list(first.keys()) if isinstance(first, dict) else type(first))
                    except Exception:
                        pass
                # 如果 displaySets 为空，但返回结构里包含 data，尝试根据 data 构造 displaySets
                if not ds and image_set.get('data'):
                    d = image_set.get('data')
                    print('image_set.data keys/type:', type(d), (list(d.keys()) if isinstance(d, dict) else 'list' if isinstance(d, list) else None))
                    series_list = None
                    if isinstance(d, dict):
                        series_list = d.get('seriesList') or d.get('series') or d.get('seriess') or d.get('result') or d.get('studies')
                    elif isinstance(d, list):
                        series_list = d
                    if series_list:
                        try:
                            # 打印第一个 series 的原始结构以便分析数据格式
                            try:
                                print('series_list[0] preview:', json.dumps(series_list[0], ensure_ascii=False)[:1000])
                            except Exception:
                                pass
                            norm = []
                            for s in series_list:
                                if not isinstance(s, dict):
                                    continue
                                # 优先使用可能存在的 'image' 字段（观察到包含 PK: 前缀的 URL 列表），再使用 'images' 或其他字段
                                images = s.get('image') or s.get('images') or s.get('instances') or s.get('imageList') or s.get('imagesList') or []
                                norm.append({'description': s.get('seriesDescription') or s.get('description') or '', 'seriesNumber': s.get('seriesNumber') or s.get('seriesNo') or '', 'images': images})
                            if norm:
                                image_set['displaySets'] = norm
                                ds = norm
                                print('构造 displaySets 长度:', len(ds))
                        except Exception as e:
                            print('构造 displaySets 时出错:', e)
        except Exception:
            pass

        # 使用页面上下文执行后续请求，确保认证一致
        # 下载逻辑（简化版，基于 xa-data 返回的 data.series 结构）
        patient = image_set.get('data', {}).get('patientname') or image_set.get('patientName') or ''
        desc = ''
        study_date = ''
        save_to = suggest_save_dir(patient, desc, study_date)
        print(f'保存到: {save_to}')

        # 规范化 series 列表
        series_list = []
        d = image_set.get('data') or {}
        if isinstance(d, dict):
            # 尝试常见字段名
            series_list = d.get('series') or d.get('seriesList') or d.get('serieslist') or []
        elif isinstance(d, list):
            series_list = d

        # （之前的调试预览逻辑已移除，继续正常处理 series_list）

        # 使用 helpers.normalize_images_field

        from pydicom import Dataset
        import base64
        from pathlib import Path
        from tqdm import tqdm
        from crawlers.tdcloud import _write_dicom

        try:
            # 调试：打印前几个 series 的原始结构，帮助分析为何 description 为空
            for si, ss in enumerate(series_list or []):
                if si < 5:
                    try:
                        print(f"series[{si}] preview:", json.dumps(ss, ensure_ascii=False)[:2000])
                    except Exception:
                        pass
            for s in series_list:
                if not isinstance(s, dict):
                    continue
                # 优先使用 SeriesNumber + seriesdescription（字段名可能大小写不一致）作为目录名
                desc_raw = s.get('seriesdescription') or s.get('seriesDescription') or s.get('description') or ''
                no_raw = s.get('seriesnumber') or s.get('seriesNumber') or s.get('seriesNo') or ''
                try:
                    no = int(no_raw)
                except Exception:
                    no = None
                if no_raw and desc_raw:
                    name = pathify(f"{str(no_raw)}_{desc_raw}") or pathify(desc_raw) or f"Series_{no_raw}"
                elif no_raw:
                    name = pathify(f"Series_{str(no_raw)}") or 'Unnamed'
                else:
                    name = pathify(desc_raw) or 'Unnamed'
                raw_images = s.get('image') or s.get('images') or s.get('instances')
                images = normalize_images_field(raw_images)

                if not images:
                    print(f'序列 {name} 没有图片条目，跳过')
                    continue

                dir_ = SeriesDirectory(save_to, no, name, int(len(images)))
                tasks = tqdm(images, desc=name, unit='张')
                for i, info in enumerate(tasks):
                    tags = None
                    img_bytes = None
                    abs_url = None

                    try:
                        img_bytes, abs_url = await fetch_image_bytes(page_for_eval, client, str(origin), info)
                        tags = build_minimal_tags(info)
                    except Exception as e:
                        print(f'处理影像条目时出错: {e}')

                    if img_bytes is None:
                        print(f"跳过序列 {name} 的第 {i} 张：无法获取像素")
                        continue

                    if not tags:
                        tags = [{'tag': '0008,0016', 'value': '1.2.840.10008.5.1.4.1.1.7'}]

                    try:
                        dst = dir_.get(i, 'dcm')
                        print(f'    写入 DICOM 到: {dst}')
                        _write_dicom(tags, img_bytes, dst)
                    except Exception as e:
                        print(f"写入 DICOM 时出错: {e}")

        finally:
            try:
                await client.close()
            except Exception:
                pass

        try:
            print('下载完成。请在浏览器中关闭页面以结束进程。')
            await (new_page or page).wait_for_event('close')
        except Exception:
            pass


async def run(url, *args):
    crawler = XaDataPlaywrightCrawler(url)
    # 使用更接近真实 iPhone 的设备参数（在 Context 创建时应用）以确保移动端 UI 正确加载
    # 这些参数模拟 iPhone 14 Pro Max 的常见特性：iOS Safari User-Agent、高 DPR、触控能力和移动视口
    iphone_viewport = {"width": 393, "height": 852}
    iphone_user_agent = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
    )
    await run_with_browser(
        crawler,
        viewport=iphone_viewport,
        user_agent=iphone_user_agent,
        is_mobile=True,
        has_touch=True,
        device_scale_factor=3,
    )
