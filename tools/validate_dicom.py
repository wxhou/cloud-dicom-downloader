#!/usr/bin/env python3
"""Validate DICOM files under a directory and print a concise report.

Usage:
  python tools/validate_dicom.py download/extracted

The script walks the directory, opens .dcm files with pydicom, and
reports successes, failures and a sample of tags for valid files.
"""
import sys
from pathlib import Path
import traceback

try:
    import pydicom
except Exception:
    print("pydicom not installed. Install with: pip install pydicom")
    raise

from tools.logging_config import get_logger

logger = get_logger(__name__)


def validate_dir(root: Path):
    logger.info(f"开始验证DICOM文件: {root}")
    
    dcm_files = list(root.rglob('*.dcm'))
    # filter out macOS resource fork files like ._xxx
    dcm_files = [p for p in dcm_files if not p.name.startswith('._')]

    total = len(dcm_files)
    ok = 0
    errors = []

    sample_info = []

    logger.info(f"发现 {total} 个DICOM文件需要验证")

    for i, p in enumerate(dcm_files):
        logger.debug(f"验证文件 ({i+1}/{total}): {p.name}")
        try:
            ds = pydicom.dcmread(str(p), force=False)
            ok += 1
            if len(sample_info) < 5:
                info = {
                    'path': str(p.relative_to(root)),
                    'PatientName': getattr(ds, 'PatientName', ''),
                    'StudyInstanceUID': getattr(ds, 'StudyInstanceUID', ''),
                    'SOPInstanceUID': getattr(ds, 'SOPInstanceUID', ''),
                    'Rows': getattr(ds, 'Rows', None),
                    'Columns': getattr(ds, 'Columns', None),
                    'TransferSyntaxUID': getattr(ds.file_meta, 'TransferSyntaxUID', None) if getattr(ds, 'file_meta', None) else None,
                }
                sample_info.append(info)
        except Exception as e:
            # capture a short traceback for the first few errors
            tb = traceback.format_exc(limit=1)
            errors.append((str(p.relative_to(root)), str(e), tb))
            logger.error(f"验证文件失败: {p.name}, 错误: {str(e)}")

    logger.info(f"验证完成: 目录={root}")
    logger.info(f"统计结果: 总文件={total}, 成功={ok}, 失败={len(errors)}")
    
    print(f"Scanned directory: {root}")
    print(f"Total .dcm files discovered: {total}")
    print(f"Successfully read: {ok}")
    print(f"Failed to read: {len(errors)}")

    if sample_info:
        print("\nSample valid files (up to 5):")
        for s in sample_info:
            print(f" - {s['path']}: PatientName={s['PatientName']}, StudyUID={s['StudyInstanceUID']}, SOP={s['SOPInstanceUID']}, {s['Rows']}x{s['Columns']}, TS={s['TransferSyntaxUID']}")

    if errors:
        print("\nFirst failures (up to 5):")
        for p, msg, tb in errors[:5]:
            print(f" - {p}: {msg}")
    
    if len(errors) > 0:
        logger.warning(f"验证过程中发现 {len(errors)} 个失败文件")
    else:
        logger.info("所有DICOM文件验证通过")

    # Return codes: 0 if all ok, 2 if some failures, 1 if none scanned
    if total == 0:
        return 1
    if len(errors) > 0:
        return 2
    return 0


if __name__ == '__main__':
    try:
        logger.info("启动DICOM文件验证工具")
        if len(sys.argv) < 2:
            print('Usage: python tools/validate_dicom.py <directory>')
            raise SystemExit(2)
        root = Path(sys.argv[1])
        if not root.exists():
            print('Directory not found:', root)
            logger.error(f"目录不存在: {root}")
            raise SystemExit(2)
        rc = validate_dir(root)
        logger.info(f"验证完成，返回代码: {rc}")
        raise SystemExit(rc)
    except Exception as e:
        logger.error(f"验证脚本执行失败: {str(e)}", exc_info=True)
        raise SystemExit(1)
