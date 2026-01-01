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
import base64
import json
import struct
import time
import zipfile
from io import BytesIO
from typing import Any, List, Optional, Tuple
from urllib.parse import urlencode

from aiohttp import ClientSession
from pydicom._dicom_dict import DicomDictionary
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.tag import Tag
from pydicom.uid import ExplicitVRLittleEndian, UID, generate_uid
from yarl import URL

# 模态到SOP Class UID映射
MODALITY_SOP_CLASS_MAP = {
    'CT': '1.2.840.10008.5.1.4.1.1.2',      # CT Image Storage
    'MR': '1.2.840.10008.5.1.4.1.1.4',      # MR Image Storage
    'US': '1.2.840.10008.5.1.4.1.1.6.1',    # Ultrasound Image Storage
    'CR': '1.2.840.10008.5.1.4.1.1.1',      # Computed Radiography Image Storage
    'DX': '1.2.840.10008.5.1.4.1.1.1.1.1',  # Digital X-Ray Image Storage
    'NM': '1.2.840.10008.5.1.4.1.1.20',     # Nuclear Medicine Image Storage
    'PT': '1.2.840.10008.5.1.4.1.1.128',    # Positron Emission Tomography Image Storage
    'XA': '1.2.840.10008.5.1.4.1.1.12.1',   # X-Ray Angiography Image Storage
    'MG': '1.2.840.10008.5.1.4.1.1.1.2.1',  # Digital Mammography Image Storage
    'RF': '1.2.840.10008.5.1.4.1.1.12.2',   # Radiofluoroscopy Image Storage
    'SR': '1.2.840.10008.5.1.4.1.1.88.33',  # Comprehensive 3D SR Storage
    'PR': '1.2.840.10008.5.1.4.1.1.481.2',  # Enhanced MR Image Storage
    'KO': '1.2.840.10008.5.1.4.1.1.481.1',  # Key Object Selection Storage
    'OT': '1.2.840.10008.5.1.4.1.1.88.59',  # Segmented Volume Storage
}


from crawlers._browser import PlaywrightCrawler, run_with_browser
from crawlers._utils import new_http_client, parse_dcm_value, pathify, SeriesDirectory, suggest_save_dir
import re


def extract_patient_info_from_page(page) -> dict:
    """从页面DOM元素中提取患者和检查信息"""
    patient_info = {}
    
    try:
        # 提取患者ID (通常显示为 ID:0000030551)
        try:
            id_element = page.query_selector('text=/ID:\d+/')
            if id_element:
                id_text = id_element.text_content()
                id_match = re.search(r'ID:(\d+)', id_text)
                if id_match:
                    patient_info['patient_id'] = id_match.group(1)
        except Exception:
            pass
        
        # 提取年龄和性别 (显示为 076Y / F)
        try:
            age_element = page.query_selector('text=/\d+Y\s*\/\s*[MF]/')
            if age_element:
                age_text = age_element.text_content()
                age_match = re.search(r'(\d+)Y\s*\/\s*([MF])', age_text)
                if age_match:
                    patient_info['age'] = age_match.group(1)
                    patient_info['sex'] = age_match.group(2)
        except Exception:
            pass
        
        # 提取序列号 (显示为 Se:101)
        try:
            series_element = page.query_selector('text=/Se:\d+/')
            if series_element:
                series_text = series_element.text_content()
                series_match = re.search(r'Se:(\d+)', series_text)
                if series_match:
                    patient_info['series_number'] = series_match.group(1)
        except Exception:
            pass
        
        # 提取图像编号 (显示为 Im:1)
        try:
            image_element = page.query_selector('text=/Im:\d+/')
            if image_element:
                image_text = image_element.text_content()
                image_match = re.search(r'Im:(\d+)', image_text)
                if image_match:
                    patient_info['image_number'] = image_match.group(1)
        except Exception:
            pass
        
        # 提取检查日期 (显示为 2025-11-27)
        try:
            date_element = page.query_selector('text=/\d{4}-\d{2}-\d{2}/')
            if date_element:
                date_text = date_element.text_content()
                date_match = re.search(r'(\d{4}-\d{2}-\d{2})', date_text)
                if date_match:
                    patient_info['study_date'] = date_match.group(1)
        except Exception:
            pass
        
        # 提取检查时间 (显示为 10:39:08)
        try:
            time_element = page.query_selector('text=/\d{2}:\d{2}:\d{2}/')
            if time_element:
                time_text = time_element.text_content()
                time_match = re.search(r'(\d{2}:\d{2}:\d{2})', time_text)
                if time_match:
                    patient_info['study_time'] = time_match.group(1).replace(':', '')
        except Exception:
            pass
        
        # 提取设备信息 (显示为 uCT 780)
        try:
            device_element = page.query_selector('text=/uCT\s+\d+/')
            if device_element:
                device_text = device_element.text_content()
                patient_info['device'] = device_text.strip()
        except Exception:
            pass
        
        # 提取扫描参数
        try:
            # 管电压 (显示为 kV:120.00)
            kv_element = page.query_selector('text=/kV:[\d.]+/')
            if kv_element:
                kv_text = kv_element.text_content()
                kv_match = re.search(r'kV:([\d.]+)', kv_text)
                if kv_match:
                    patient_info['kv'] = kv_match.group(1)
            
            # 管电流 (显示为 mA:38)
            ma_element = page.query_selector('text=/mA:\d+/')
            if ma_element:
                ma_text = ma_element.text_content()
                ma_match = re.search(r'mA:(\d+)', ma_text)
                if ma_match:
                    patient_info['ma'] = ma_match.group(1)
        except Exception:
            pass
        
        # 提取窗口设置
        try:
            # 窗宽 (显示为 WW:145)
            ww_element = page.query_selector('text=/WW:\d+/')
            if ww_element:
                ww_text = ww_element.text_content()
                ww_match = re.search(r'WW:(\d+)', ww_text)
                if ww_match:
                    patient_info['window_width'] = ww_match.group(1)
            
            # 窗位 (显示为 WL:-931)
            wl_element = page.query_selector('text=/WL:-?\d+/')
            if wl_element:
                wl_text = wl_element.text_content()
                wl_match = re.search(r'WL:(-?\d+)', wl_text)
                if wl_match:
                    patient_info['window_level'] = wl_match.group(1)
        except Exception:
            pass
        
        # 提取图像尺寸 (显示为 768x672)
        try:
            size_element = page.query_selector('text=/\d+x\d+/')
            if size_element:
                size_text = size_element.text_content()
                size_match = re.search(r'(\d+)x(\d+)', size_text)
                if size_match:
                    patient_info['image_width'] = size_match.group(1)
                    patient_info['image_height'] = size_match.group(2)
        except Exception:
            pass
        
        print(f"从页面提取的患者信息: {patient_info}")
        return patient_info
        
    except Exception as e:
        print(f"提取患者信息时出错: {e}")
        return {}


def normalize_images_field(raw: Any) -> List[Any]:
    """Return a normalized list of image entries (strings or dicts)."""
    res = []
    if raw is None:
        return res
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, (str, dict)):
                res.append(it)
        return res
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get('arrayValue'):
                for entry in parsed.get('arrayValue', []):
                    if isinstance(entry, str):
                        try:
                            inner = json.loads(entry)
                            if isinstance(inner, list):
                                for item in inner:
                                    res.append(item)
                            elif isinstance(inner, dict):
                                res.append(inner)
                            else:
                                res.append(entry)
                        except Exception:
                            res.append(entry)
                    else:
                        res.append(entry)
            elif isinstance(parsed, list):
                for item in parsed:
                    res.append(item)
            else:
                res.append(raw)
        except Exception:
            res.append(raw)
    return res


async def fetch_image_bytes(page_for_eval, client, origin: str, info: Any) -> Tuple[Optional[bytes], Optional[str]]:
    """Try to fetch image bytes using the browser (same-origin) then aiohttp fallback.

    Returns (img_bytes or None, abs_url or None).
    """
    img_bytes = None
    abs_url = None
    try:
        if isinstance(info, str) and info.startswith('PK:'):
            oss = info.split(':', 1)[1].lstrip('/')
            abs_url = str(origin) + '/' + oss.lstrip('/')
            try:
                js = (
                    "async (url) => { const r = await fetch(url, {credentials: 'same-origin'});"
                    " if(!r.ok) throw new Error('fetch failed ' + r.status); const buf = await r.arrayBuffer();"
                    " const bytes = new Uint8Array(buf); let binary = ''; const chunk = 0x8000;"
                    " for(let i=0;i<bytes.length;i+=chunk){ binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i,i+chunk))); }"
                    " return btoa(binary); }"
                )
                b64 = await page_for_eval.evaluate(js, abs_url)
                img_bytes = base64.b64decode(b64)
            except Exception:
                img_bytes = None
        elif isinstance(info, dict):
            oss = info.get('ossKey') or info.get('file') or info.get('fileHash')
            if oss:
                abs_url = str(origin) + '/' + str(oss).lstrip('/')
                try:
                    js = (
                        "async (url) => { const r = await fetch(url, {credentials: 'same-origin'});"
                        " if(!r.ok) throw new Error('fetch failed ' + r.status); const buf = await r.arrayBuffer();"
                        " const bytes = new Uint8Array(buf); let binary = ''; const chunk = 0x8000;"
                        " for(let i=0;i<bytes.length;i+=chunk){ binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i,i+chunk))); }"
                        " return btoa(binary); }"
                    )
                    b64 = await page_for_eval.evaluate(js, abs_url)
                    img_bytes = base64.b64decode(b64)
                except Exception:
                    img_bytes = None
    except Exception:
        pass

    # aiohttp fallback if browser fetch failed
    if img_bytes is None and abs_url:
        try:
            async with client.get(abs_url) as resp:
                data = await resp.read()
                if data and (data.startswith(b'{') or data.startswith(b'[')):
                    try:
                        txt = data.decode('utf-8', errors='ignore')
                        j = json.loads(txt)
                        if isinstance(j, dict):
                            b64_val = j.get('b64')
                            if b64_val:
                                img_bytes = base64.b64decode(b64_val)
                    except Exception:
                        pass
                else:
                    img_bytes = data
        except Exception:
            img_bytes = None

    return img_bytes, abs_url


def build_minimal_tags(info: Any, patient_info: dict | None = None) -> List[dict]:
    tags = []
    try:
        if isinstance(info, dict):
            if info.get('sopClassUid'):
                tags.append({'tag': '0008,0016', 'value': info.get('sopClassUid')})
            if info.get('instanceUid'):
                tags.append({'tag': '0008,0018', 'value': info.get('instanceUid')})
            if info.get('rows'):
                tags.append({'tag': '0028,0010', 'value': str(info.get('rows'))})
            if info.get('columns'):
                tags.append({'tag': '0028,0011', 'value': str(info.get('columns'))})
    except Exception:
        pass

    # 动态设置SOP Class UID
    modality = None
    if patient_info and patient_info.get('modality'):
        modality = patient_info['modality']
    elif isinstance(info, dict) and info.get('modality'):
        modality = info.get('modality')
    
    # 确定SOP Class UID
    sop_class_uid = None
    if not any(tag['tag'] == '0008,0016' for tag in tags):
        if modality and modality.upper() in MODALITY_SOP_CLASS_MAP:
            sop_class_uid = MODALITY_SOP_CLASS_MAP[modality.upper()]
        else:
            # 默认使用CT模态
            sop_class_uid = '1.2.840.10008.5.1.4.1.1.2'  # CT Image Storage
        tags.append({'tag': '0008,0016', 'value': sop_class_uid})
    
    # 设置SOP Instance UID
    if not any(tag['tag'] == '0008,0018' for tag in tags):
        tags.append({'tag': '0008,0018', 'value': '1.2.3.4.5.6.7.8.9.10'})  # SOP Instance UID
    
    # 使用页面提取的图像尺寸
    if patient_info and patient_info.get('image_width') and patient_info.get('image_height'):
        tags.append({'tag': '0028,0010', 'value': patient_info['image_height']})  # Rows
        tags.append({'tag': '0028,0011', 'value': patient_info['image_width']})   # Columns
    else:
        if not any(tag['tag'] == '0028,0010' for tag in tags):
            tags.append({'tag': '0028,0010', 'value': '512'})  # Rows
        if not any(tag['tag'] == '0028,0011' for tag in tags):
            tags.append({'tag': '0028,0011', 'value': '512'})  # Columns

    # 添加从页面提取的患者信息
    if patient_info:
        if patient_info.get('patient_id'):
            tags.append({'tag': '0010,0020', 'value': patient_info['patient_id']})  # Patient ID
        
        if patient_info.get('age'):
            tags.append({'tag': '0010,1010', 'value': patient_info['age']})  # Patient Age
        
        if patient_info.get('sex'):
            sex_map = {'M': 'M', 'F': 'F'}
            if patient_info['sex'] in sex_map:
                tags.append({'tag': '0010,0040', 'value': sex_map[patient_info['sex']]})  # Patient Sex
        
        if patient_info.get('series_number'):
            tags.append({'tag': '0020,0011', 'value': patient_info['series_number']})  # Series Number
        
        if patient_info.get('image_number'):
            tags.append({'tag': '0020,0013', 'value': patient_info['image_number']})  # Instance Number
        
        if patient_info.get('study_date'):
            tags.append({'tag': '0008,0020', 'value': patient_info['study_date'].replace('-', '')})  # Study Date
        
        if patient_info.get('study_time'):
            tags.append({'tag': '0008,0030', 'value': patient_info['study_time']})  # Study Time
        
        if patient_info.get('kv'):
            tags.append({'tag': '0018,0050', 'value': patient_info['kv']})  # Slice Thickness (kV)
            tags.append({'tag': '0018,0060', 'value': patient_info['kv']})  # KVP
        
        if patient_info.get('ma'):
            tags.append({'tag': '0018,1151', 'value': patient_info['ma']})  # XRay Tube Current
        
        if patient_info.get('device'):
            tags.append({'tag': '0008,0070', 'value': 'UIH'})  # Manufacturer
            tags.append({'tag': '0008,1090', 'value': patient_info['device']})  # Manufacturer Model Name
    
    # 其他必需标签
    tags.append({'tag': '0028,0100', 'value': '16'})  # Bits Allocated
    tags.append({'tag': '0028,0002', 'value': '1'})   # Samples per Pixel
    tags.append({'tag': '0028,0004', 'value': 'MONOCHROME2'})  # Photometric Interpretation
    tags.append({'tag': '0028,0101', 'value': '16'})  # Bits Stored
    tags.append({'tag': '0028,0102', 'value': '15'})  # High Bit
    tags.append({'tag': '0028,0103', 'value': '0'})   # Pixel Representation
    
    # 添加Study和Series UID（如果从patient_info获取）
    if patient_info:
        if patient_info.get('study_instance_uid'):
            tags.append({'tag': '0020,000D', 'value': patient_info['study_instance_uid']})  # Study Instance UID
        
        if patient_info.get('series_instance_uid'):
            tags.append({'tag': '0020,000E', 'value': patient_info['series_instance_uid']})  # Series Instance UID
        
        if patient_info.get('accession_number'):
            tags.append({'tag': '0008,0050', 'value': patient_info['accession_number']})  # Accession Number
        
        if patient_info.get('study_id'):
            tags.append({'tag': '0020,0010', 'value': patient_info['study_id']})  # Study ID
        
        if patient_info.get('patient_birth_date'):
            tags.append({'tag': '0010,0030', 'value': patient_info['patient_birth_date']})  # Patient Birth Date
    
    return tags


def parse_jpeg_header(data: bytes):
    if len(data) < 2 or data[:2] != b'\xff\xd8':
        return None
    
    length = len(data)
    index = 2
    
    while index < length:
        if data[index] != 0xFF:
            index += 1
            continue
            
        marker = data[index + 1]
        index += 2
        
        if marker == 0xC0:
            if index + 8 > length:
                return None
            
            precision = data[index + 2]
            height = struct.unpack('>H', data[index + 3:index + 5])[0]
            width = struct.unpack('>H', data[index + 5:index + 7])[0]
            channels = data[index + 7]
            
            return {
                'height': height,
                'width': width,
                'channels': channels,
                'precision': precision
            }
            
        if index + 2 > length:
            return None
        segment_len = struct.unpack('>H', data[index:index + 2])[0]
        
        if marker == 0xDA:
            break
            
        index += segment_len
        
    return None


def _write_dicom(tag_list: list, image: bytes, filename, patient_info: dict | None = None):
    try:
        debug_jpg_path = filename + ".debug.jpg"
        with open(debug_jpg_path, "wb") as f:
            f.write(image)
    except Exception:
        pass

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.SpecificCharacterSet = 'ISO_IR 192'

    for item in tag_list:
        try:
            tag = Tag(item["tag"].split(",", 2))
            definition = DicomDictionary.get(tag)
            val = item["value"]
            if tag.group == 2:
                if definition:
                    vr, key = definition[0], definition[4]
                    setattr(ds.file_meta, key, parse_dcm_value(val, vr))
            elif definition:
                vr, key = definition[0], definition[4]
                setattr(ds, key, parse_dcm_value(val, vr))
            else:
                ds.add_new(tag, "LO", val)
        except Exception:
            pass

    if patient_info:
        if patient_info.get('patient_name'):
            ds.PatientName = patient_info['patient_name']
        ds.Modality = patient_info.get('modality', 'CT')
        if not hasattr(ds, 'StudyInstanceUID') or not ds.StudyInstanceUID:
            ds.StudyInstanceUID = generate_uid()
        if not hasattr(ds, 'SeriesInstanceUID') or not ds.SeriesInstanceUID:
            ds.SeriesInstanceUID = generate_uid()

    ds.file_meta.ImplementationClassUID = UID('1.2.826.0.1.3680043.8.498')
    ds.file_meta.ImplementationVersionName = 'XA-DATA-PY'
    
    if not hasattr(ds, 'SOPClassUID'):
         ds.SOPClassUID = UID('1.2.840.10008.5.1.4.1.1.2')
    
    ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
    if hasattr(ds, 'SOPInstanceUID'):
        ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    else:
        new_uid = generate_uid()
        ds.SOPInstanceUID = new_uid
        ds.file_meta.MediaStorageSOPInstanceUID = new_uid

    jpeg_info = parse_jpeg_header(image)

    def _is_zip_encapsulated(data: bytes) -> bool:
        """检查数据是否已经是ZIP封装格式"""
        if len(data) < 4:
            return False
        # ZIP 封装格式通常以 PK 开头 (504B)
        return data[:2] == b'PK' or b'PK' in data[:256]

    def _extract_jpeg2000_from_zip(data: bytes) -> Optional[bytes]:
        """从ZIP数据中提取JPEG 2000原始数据"""
        try:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                # 获取ZIP中的文件列表
                for name in zf.namelist():
                    # 查找可能包含图像数据的文件
                    if not name.endswith('/'):  # 跳过目录
                        content = zf.read(name)
                        # 检查是否是 JPEG 2000 数据
                        if content.startswith(b'\xff\x4f') or b'ftyp' in content[:64]:
                            return content
                        # 也可能是普通 JPEG
                        if content.startswith(b'\xff\xd8'):
                            return content
            # 如果没找到，返回原始数据
            return data
        except Exception as e:
            # 如果不是有效的ZIP，返回原始数据
            return data

    # 设置Transfer Syntax并决定是否需要封装
    if jpeg_info:
        # JPEG 格式
        ds.file_meta.TransferSyntaxUID = UID('1.2.840.10008.1.2.4.50')
        is_compressed = True
        ds.Rows = jpeg_info['height']
        ds.Columns = jpeg_info['width']
        ds.SamplesPerPixel = jpeg_info['channels']
        ds.BitsAllocated = 8
        ds.BitsStored = 8
        ds.HighBit = 7
        ds.PixelRepresentation = 0

        if jpeg_info['channels'] == 3:
            ds.PhotometricInterpretation = 'YBR_FULL_422'
            ds.PlanarConfiguration = 0
        else:
            ds.PhotometricInterpretation = 'MONOCHROME2'

        tags_to_delete = [
            'RescaleIntercept', 'RescaleSlope', 'RescaleType',
            'WindowCenter', 'WindowWidth', 'WindowCenterWidthExplanation'
        ]

        for tag_name in tags_to_delete:
            if hasattr(ds, tag_name):
                delattr(ds, tag_name)

        ds.WindowCenter = '128'
        ds.WindowWidth = '256'

    elif image.startswith(b'\xff\x4f') or b'ftyp' in image[:64]:
        # JPEG 2000 格式 (原始数据)
        ds.file_meta.TransferSyntaxUID = UID('1.2.840.10008.1.2.4.90')
        is_compressed = True
        if not hasattr(ds, 'BitsAllocated'): ds.BitsAllocated = 16
        if not hasattr(ds, 'Rows'): ds.Rows = 512
        if not hasattr(ds, 'Columns'): ds.Columns = 512

    else:
        # 检查是否是已经封装的数据（服务器返回的ZIP封装）
        if _is_zip_encapsulated(image):
            # 从 ZIP 中提取原始 JPEG 2000 数据
            raw_data = _extract_jpeg2000_from_zip(image)
            if raw_data.startswith(b'\xff\x4f') or b'ftyp' in raw_data[:64]:
                # JPEG 2000 数据
                ds.file_meta.TransferSyntaxUID = UID('1.2.840.10008.1.2.4.90')  # JPEG 2000 Lossless
                is_compressed = True
                image = raw_data  # 使用提取的原始数据
            else:
                # 其他封装数据，使用 Explicit VR Little Endian
                ds.file_meta.TransferSyntaxUID = UID('1.2.840.10008.1.2.1')
                is_compressed = False
            if not hasattr(ds, 'BitsAllocated'): ds.BitsAllocated = 16
            if not hasattr(ds, 'Rows'): ds.Rows = 512
            if not hasattr(ds, 'Columns'): ds.Columns = 512
        else:
            # 真正的未压缩数据
            ds.file_meta.TransferSyntaxUID = UID('1.2.840.10008.1.2.1')
            is_compressed = False
            try:
                rows = int(ds.Rows) if hasattr(ds, 'Rows') else 512
                cols = int(ds.Columns) if hasattr(ds, 'Columns') else 512
                if len(image) == rows * cols:
                    ds.BitsAllocated = 8
                    ds.BitsStored = 8
                    ds.HighBit = 7
            except:
                pass

    # 只有当数据是原始压缩格式时才封装
    if is_compressed:
        ds.PixelData = encapsulate([image])
    else:
        ds.PixelData = image

    ds.save_as(filename, enforce_file_format=True)


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
        
        # 初始化患者信息为空
        patient_info = {}

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
            print('未获取到 image_set，无法继续下载')
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
        # 提取患者信息
        if image_set and isinstance(image_set, dict) and 'data' in image_set:
            api_data = image_set['data']
            patient_info = {
                'patient_name': api_data.get('patientname', ''),
                'patient_id': api_data.get('checkserialnum', ''),
                'sex': api_data.get('sex', ''),
                'modality': api_data.get('modality', 'CT'),
                'study_instance_uid': api_data.get('studyInstanceUID', ''),
                'accession_number': api_data.get('accessionNumber', ''),
                'study_id': api_data.get('studyId', ''),
            }
            print(f"从API数据提取患者信息: {patient_info}")
        
        # 优先使用从API提取的患者信息
        patient = patient_info.get('patient_name') or image_set.get('data', {}).get('patientname') or image_set.get('patientName') or ''
        
        # 如果患者姓名为空，尝试从URL或其他来源提取
        if not patient:
            # 从URL参数中提取可能的患者信息
            try:
                url_params = URL(self.report_url).query
                title = url_params.get('title', '')
                # 解码URL编码的中文
                if '%' in title:
                    import urllib.parse
                    try:
                        decoded_title = urllib.parse.unquote(title, encoding='utf-8')
                        patient = decoded_title.replace('西安市影像云-', '').replace('*', '').strip()
                    except Exception:
                        patient = title.replace('西安市影像云-', '').replace('*', '').strip()
                else:
                    patient = title.replace('西安市影像云-', '').replace('*', '').strip()
            except Exception:
                # 最后的备选方案：使用默认名称
                patient = '患者' + patient_info.get('patient_id', 'Unknown')
        
        # 确保患者姓名不为空
        if not patient or patient.strip() == '':
            patient = '患者' + patient_info.get('patient_id', 'Unknown')
        
        # 合并从API和页面获取的患者信息
        if patient_info:
            patient_info['patient_name'] = patient
        
        desc = ''
        study_date = patient_info.get('study_date', '') or ''
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

        from pathlib import Path
        from tqdm import tqdm

        try:
            print(f"发现 {len(series_list)} 个序列")
            
            series_options = []
            for i, s in enumerate(series_list):
                if not isinstance(s, dict):
                    continue
                desc_raw = s.get('seriesdescription') or s.get('seriesDescription') or s.get('description') or ''
                no_raw = s.get('seriesnumber') or s.get('seriesNumber') or s.get('seriesNo') or ''
                try:
                    no = int(no_raw) if no_raw else 0
                except:
                    no = 0
                images_count = 0
                raw_images = s.get('image') or s.get('images') or s.get('instances')
                if raw_images:
                    if isinstance(raw_images, list):
                        images_count = len(raw_images)
                    elif isinstance(raw_images, str):
                        try:
                            images_count = len(json.loads(raw_images))
                        except:
                            pass
                series_options.append({'index': i, 'no': no, 'desc': desc_raw, 'count': images_count})
                print(f"  [{i}] 序号:{no} | 描述:{desc_raw} | 图片数:{images_count}")
            
            print("\n请选择要下载的序列 (支持以下方式)：")
            print("  输入单个编号: 0 或 2 (下载第1个或第3个序列)")
            print("  输入范围: 0-3 (下载第1到第4个序列)")
            print("  输入 all (下载所有序列)")
            
            try:
                user_input = input("请输入选择: ").strip().lower()
                if user_input == 'all' or not user_input:
                    selected_indices = list(range(len(series_options)))
                    print(f"将下载所有 {len(selected_indices)} 个序列")
                elif '-' in user_input:
                    parts = user_input.split('-')
                    if len(parts) == 2:
                        start = int(parts[0].strip())
                        end = int(parts[1].strip())
                        selected_indices = list(range(start, end + 1))
                        print(f"将下载第 {start} 到 {end} 个序列")
                    else:
                        selected_indices = list(range(len(series_options)))
                else:
                    indices = [int(x.strip()) for x in user_input.split(',')]
                    selected_indices = [i for i in indices if 0 <= i < len(series_options)]
                    print(f"将下载序列: {selected_indices}")
            except Exception as e:
                print(f"输入错误，使用默认下载所有序列: {e}")
                selected_indices = list(range(len(series_options)))
            
            for idx, s in enumerate(series_list):
                if not isinstance(s, dict):
                    continue
                
                if idx not in selected_indices:
                    continue
                
                desc_raw = s.get('seriesdescription') or s.get('seriesDescription') or s.get('description') or ''
                no_raw = s.get('seriesnumber') or s.get('seriesNumber') or s.get('seriesNo') or ''
                try:
                    no = int(no_raw) if no_raw else None
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
                        # 从series中提取series instance UID
                        series_instance_uid = s.get('seriesInstanceUID') or s.get('seriesUid') or s.get('seriesuid')
                        if series_instance_uid and patient_info:
                            patient_info['series_instance_uid'] = series_instance_uid
                        tags = build_minimal_tags(info, patient_info)
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
                        _write_dicom(tags, img_bytes, dst, patient_info)
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
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    await run_with_browser(
        crawler,
        viewport=iphone_viewport,
        user_agent=iphone_user_agent,
        is_mobile=True,
        has_touch=True,
        device_scale_factor=3,
    )
