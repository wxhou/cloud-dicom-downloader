"""Convert JP2-in-DICOM PixelData to raw JPEG2000 codestream fragments.

This script scans a directory for .dcm files whose PixelData appear to
contain a JP2 file (contains 'ftyp'). For each such file it extracts the
`jp2c` box (the codestream) and rewrites the DICOM PixelData as an
encapsulated fragment containing the codestream, setting the
TransferSyntaxUID to JPEG2000 Lossless. The output file is written next
to the input file with suffix `_j2k.dcm`.

This often fixes viewers that expect raw JPEG2000 codestreams rather than
the JP2 file format wrapped inside PixelData.
"""
import sys
from pathlib import Path
import binascii
from pydicom import dcmread
from pydicom.dataset import FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import JPEG2000Lossless


def extract_jp2c(jp2_bytes: bytes) -> bytes | None:
    """Parse JP2 boxes and return the data of the first 'jp2c' box.

    This implements minimal JP2 box parsing sufficient for common files.
    Returns None if no 'jp2c' box is found.
    """
    # locate the 'ftyp' box; JP2 file may be embedded with leading bytes
    ftyp_idx = jp2_bytes.find(b'ftyp')
    if ftyp_idx == -1:
        # fallback to start
        i = 0
    else:
        # length field is 4 bytes before the box type
        i = max(0, ftyp_idx - 4)
    L = len(jp2_bytes)
    while i + 8 <= L:
        # 4-byte length (big-endian), 4-byte type
        length = int.from_bytes(jp2_bytes[i:i+4], "big")
        box_type = jp2_bytes[i+4:i+8]
        header_len = 8
        if length == 1:
            # 64-bit largesize follows
            if i + 16 > L:
                break
            length = int.from_bytes(jp2_bytes[i+8:i+16], "big")
            header_len = 16
        if length == 0:
            # box extends to end of file
            box_data_start = i + header_len
            box_data = jp2_bytes[box_data_start:]
            if box_type == b'jp2c':
                return box_data
            break

        box_data_start = i + header_len
        box_data_end = i + length
        if box_data_end > L:
            break

        if box_type == b'jp2c':
            return jp2_bytes[box_data_start:box_data_end]

        i = box_data_end

    return None


def convert_file(path: Path) -> bool:
    ds = dcmread(path, force=True)
    pd = ds.PixelData
    if b'ftyp' not in pd[:64]:
        return False

    codestream = extract_jp2c(pd)
    if codestream is None:
        print(f"{path}: jp2c box not found, skipping")
        return False

    ds.PixelData = encapsulate([codestream])
    if not hasattr(ds, 'file_meta'):
        ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = JPEG2000Lossless

    out = path.with_name(path.stem + "_j2k" + path.suffix)
    ds.save_as(out, write_like_original=False)
    print(f"Wrote {out}")
    return True


def main(argv):
    if len(argv) < 2:
        print("Usage: convert_jp2_to_j2k.py <folder-or-file>")
        return 2

    p = Path(argv[1])
    files = []
    if p.is_dir():
        files = list(p.rglob('*.dcm'))
    elif p.is_file():
        files = [p]
    else:
        print("Path not found", p)
        return 2

    converted = 0
    for f in files:
        try:
            if convert_file(f):
                converted += 1
        except Exception as e:
            print(f"Error converting {f}: {e}")

    print(f"Converted {converted}/{len(files)} files")
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
