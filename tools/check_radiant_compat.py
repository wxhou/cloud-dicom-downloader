#!/usr/bin/env python3
import argparse
import os
from collections import Counter, defaultdict
import pydicom


def analyze_dir(path, max_samples=10):
    ts_counts = Counter()
    photometric = Counter()
    bits = Counter()
    samples = Counter()
    total = 0
    unreadable = 0
    ftyp_count = 0
    ftyp_samples = []
    problem_samples = []

    for root, _, files in os.walk(path):
        for fn in files:
            if not fn.lower().endswith('.dcm'):
                continue
            total += 1
            fpath = os.path.join(root, fn)
            try:
                ds = pydicom.dcmread(fpath, stop_before_pixels=True, force=True)
            except Exception as e:
                unreadable += 1
                if len(problem_samples) < max_samples:
                    problem_samples.append((fpath, f'read-error: {e}'))
                continue
            ts = ds.file_meta.get('TransferSyntaxUID', None)
            if ts is None:
                ts = 'missing'
            ts_counts[str(ts)] += 1
            photometric[ds.get('PhotometricInterpretation', 'missing')] += 1
            bits[ds.get('BitsAllocated', 'missing')] += 1
            samples[ds.get('SamplesPerPixel', 'missing')] += 1

            # Check for 'ftyp' in file bytes (JP2 box marker)
            try:
                with open(fpath, 'rb') as f:
                    data = f.read()
                if b'ftyp' in data:
                    ftyp_count += 1
                    if len(ftyp_samples) < max_samples:
                        ftyp_samples.append(fpath)
            except Exception as e:
                if len(problem_samples) < max_samples:
                    problem_samples.append((fpath, f'binary-read-error: {e}'))

    print(f'Total .dcm files scanned: {total}')
    print(f'Unreadable by pydicom: {unreadable}')
    print('\nTransferSyntaxUID distribution (top):')
    for ts, c in ts_counts.most_common():
        print(f'  {ts}: {c}')
    print('\nPhotometricInterpretation counts:')
    for k, v in photometric.items():
        print(f'  {k}: {v}')
    print('\nBitsAllocated counts:')
    for k, v in bits.items():
        print(f'  {k}: {v}')
    print('\nSamplesPerPixel counts:')
    for k, v in samples.items():
        print(f'  {k}: {v}')
    print(f"\nFiles containing 'ftyp' (likely JP2-wrapped): {ftyp_count}")
    if ftyp_samples:
        print('\nExample files with "ftyp":')
        for s in ftyp_samples:
            print('  ' + s)
    if problem_samples:
        print('\nExample problem files:')
        for p, reason in problem_samples:
            print(f'  {p} -> {reason}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Check DICOM compatibility for RadiAnt-like viewers.')
    parser.add_argument('path', help='Directory to scan')
    parser.add_argument('--samples', type=int, default=10, help='Number of example files to show for issues')
    args = parser.parse_args()
    if not os.path.exists(args.path):
        print('Path does not exist:', args.path)
        raise SystemExit(1)
    analyze_dir(args.path, max_samples=args.samples)
