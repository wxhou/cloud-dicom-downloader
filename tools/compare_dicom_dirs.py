#!/usr/bin/env python3
"""比较两个包含 DICOM 文件的目录，输出文件集差异与每个共同文件的关键 DICOM 元数据差异。

用法:
    python tools/compare_dicom_dirs.py <dir1> <dir2>

输出示例:
 - 列出仅存在于 dir1 或 dir2 的文件
 - 对于同时存在的文件，打印 TransferSyntaxUID、Rows/Columns、BitsAllocated、SOPClassUID、SOPInstanceUID、PixelData 是否包含 JP2 header (ftyp)、像素数据哈希
"""
from pathlib import Path
import sys
import hashlib
from typing import Dict, Any

from pydicom import dcmread


def gather_dcms(root: Path) -> Dict[Path, Path]:
    res = {}
    for p in root.rglob('*.dcm'):
        try:
            rel = p.relative_to(root)
        except Exception:
            rel = p.name
        res[rel] = p
    return res


def file_info(p: Path) -> Dict[str, Any]:
    info = {
        'path': str(p),
        'size': p.stat().st_size,
        'read_error': None,
    }
    try:
        ds = dcmread(p, force=True)
        fm = getattr(ds, 'file_meta', None)
        ts = getattr(fm, 'TransferSyntaxUID', None) if fm else None
        info.update({
            'transfer_syntax': str(ts) if ts is not None else None,
            'sop_class': str(getattr(ds, 'SOPClassUID', None)),
            'sop_instance': str(getattr(ds, 'SOPInstanceUID', None)),
            'rows': getattr(ds, 'Rows', None),
            'columns': getattr(ds, 'Columns', None),
            'bits_allocated': getattr(ds, 'BitsAllocated', None),
        })
        pd = None
        try:
            pd = getattr(ds, 'PixelData', None)
        except Exception:
            pd = None
        if pd:
            head = pd[:64] if isinstance(pd, (bytes, bytearray)) else b''
            info['pixel_ftyp'] = b'ftyp' in head
            info['pixel_jpeg_soi'] = head[:3] == b'\xff\xd8\xff'
            # 整个像素数据哈希，可能较大但能准确判断像素差异
            try:
                h = hashlib.sha256()
                if isinstance(pd, (bytes, bytearray)):
                    h.update(pd)
                else:
                    h.update(bytes(pd))
                info['pixel_hash'] = h.hexdigest()
            except Exception:
                info['pixel_hash'] = None
        else:
            info['pixel_ftyp'] = False
            info['pixel_jpeg_soi'] = False
            info['pixel_hash'] = None
    except Exception as e:
        info['read_error'] = str(e)
    return info


def compare_dirs(d1: Path, d2: Path):
    a = gather_dcms(d1)
    b = gather_dcms(d2)

    a_set = set(a.keys())
    b_set = set(b.keys())

    only_a = sorted(a_set - b_set)
    only_b = sorted(b_set - a_set)
    common = sorted(a_set & b_set)

    print(f"目录1: {d1} 发现 {len(a)} DICOM 文件")
    print(f"目录2: {d2} 发现 {len(b)} DICOM 文件")
    print(f"仅在目录1: {len(only_a)} 个文件")
    for p in only_a[:50]:
        print('  -', p)
    if len(only_a) > 50:
        print('  ...')
    print(f"仅在目录2: {len(only_b)} 个文件")
    for p in only_b[:50]:
        print('  -', p)
    if len(only_b) > 50:
        print('  ...')

    print(f"共同文件: {len(common)} 个，开始比较元数据差异...\n")

    diffs = []
    for rel in common:
        p1 = a[rel]
        p2 = b[rel]
        i1 = file_info(p1)
        i2 = file_info(p2)
        if i1.get('read_error') or i2.get('read_error'):
            diffs.append((rel, 'read_error', i1.get('read_error'), i2.get('read_error')))
            continue
        keys = ['transfer_syntax', 'rows', 'columns', 'bits_allocated', 'sop_class', 'sop_instance', 'pixel_ftyp', 'pixel_jpeg_soi', 'pixel_hash', 'size']
        local_diff = {}
        for k in keys:
            v1 = i1.get(k)
            v2 = i2.get(k)
            if v1 != v2:
                local_diff[k] = (v1, v2)
        if local_diff:
            diffs.append((rel, local_diff))

    print(f"发现 {len(diffs)} 个有差异的共同文件\n")
    for item in diffs:
        rel = item[0]
        print('文件:', rel)
        if item[1] == 'read_error':
            print('  无法读取:', item[2], item[3])
            continue
        for k, (v1, v2) in item[1].items():
            print(f"  {k}:\n    目录1 -> {v1}\n    目录2 -> {v2}")
        print('')

    if not diffs:
        print('共同文件元数据全部一致（在比较的字段范围内）')


def main():
    if len(sys.argv) != 3:
        print('用法: python tools/compare_dicom_dirs.py <dir1> <dir2>')
        sys.exit(2)
    d1 = Path(sys.argv[1])
    d2 = Path(sys.argv[2])
    if not d1.exists() or not d2.exists():
        print('指定目录不存在')
        sys.exit(2)
    compare_dirs(d1, d2)


if __name__ == '__main__':
    main()
