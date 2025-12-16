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


def validate_dir(root: Path):
    dcm_files = list(root.rglob('*.dcm'))
    # filter out macOS resource fork files like ._xxx
    dcm_files = [p for p in dcm_files if not p.name.startswith('._')]

    total = len(dcm_files)
    ok = 0
    errors = []

    sample_info = []

    for i, p in enumerate(dcm_files):
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

    # Return codes: 0 if all ok, 2 if some failures, 1 if none scanned
    if total == 0:
        return 1
    if len(errors) > 0:
        return 2
    return 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python tools/validate_dicom.py <directory>')
        raise SystemExit(2)
    root = Path(sys.argv[1])
    if not root.exists():
        print('Directory not found:', root)
        raise SystemExit(2)
    rc = validate_dir(root)
    raise SystemExit(rc)
