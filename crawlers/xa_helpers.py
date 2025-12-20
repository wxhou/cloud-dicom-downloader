"""Helpers for xa-data crawler: image parsing and fetching utilities."""
import json
import base64
from typing import Any, List, Tuple


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


async def fetch_image_bytes(page_for_eval, client, origin: str, info: Any) -> Tuple[bytes, str]:
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


def build_minimal_tags(info: Any) -> List[dict]:
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
    # sensible defaults
    tags.append({'tag': '0028,0100', 'value': '16'})
    tags.append({'tag': '0028,0002', 'value': '1'})
    tags.append({'tag': '0028,0004', 'value': 'MONOCHROME2'})
    return tags
