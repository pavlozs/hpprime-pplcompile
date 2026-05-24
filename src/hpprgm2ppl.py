#!/usr/bin/env python3
"""
hpprgm2ppl.py – Decompile HP Prime binary (.hpprgm) to HP PPL text source (.ppl)

Each program block inside the .hpprgm produces one .ppl file named after the program.

Usage:
    python hpprgm2ppl.py input.hpprgm output_dir/
"""

import json
import re
import sys
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# .hpprgm binary format (reverse-engineered from HP Prime Connectivity Kit output)
#
# File layout:
#   [0x00 – 0x3F]  Global header (64 bytes)
#   [0x40 – ...]   Catalog section: N × 88-byte entries, marker = 0b 02 40 00
#   [...]          Program data blocks, each starting with a 4-byte size field,
#                  then 4 bytes constant, then 8b 00 40 00 marker + name + source
#
# Program data block structure:
#   +0x00  uint32 LE  block_data_size  (= bytes following this field to block end)
#   +0x04  4 bytes    constant [44 00 00 00]
#   +0x08  4 bytes    block marker [8b 00 40 00]
#   +0x0C  64 bytes   program name (UTF-16-LE, zero-padded)
#   +0x4C  4 bytes    [08 00 00 00]
#   +0x50  4 bytes    [85 00 80 00]
#   +0x54  4 bytes    [00 00 00 00]
#   +0x58  uint32 LE  source_payload_size
#   +0x5C  2 bytes    source marker  [9b 00]  (U+009B)
#   +0x5E  2 bytes    source prefix  [c0 00]  (U+00C0 – HP PPL version tag)
#   +0x60  N bytes    source text (UTF-16-LE, without BOM)
#   +0x60+N 2 bytes   null terminator [00 00]
# ---------------------------------------------------------------------------

BLOCK_MARKER  = b'\x8b\x00\x40\x00'
SOURCE_MARKER = b'\x9b\x00'
SOURCE_PREFIX = b'\xc0\x00'   # U+00C0 – HP PPL version tag, not part of source text
NAME_SIZE     = 64             # bytes (32 UTF-16-LE chars)


def _read_utf16_name(data: bytes, offset: int, max_bytes: int = NAME_SIZE) -> str:
    raw = data[offset:offset + max_bytes]
    return raw.decode('utf-16-le', errors='replace').split('\x00')[0]


def _find_null_end(data: bytes, start: int) -> int:
    """Return byte offset of the 00 00 null terminator starting at or after `start`."""
    i = start
    while i + 1 < len(data):
        if data[i] == 0 and data[i + 1] == 0:
            return i
        i += 2
    return len(data)


def extract_programs(data: bytes) -> list[tuple[str, str]]:
    """
    Return list of (program_name, source_text) from all program blocks.
    Scans for 8b 00 40 00 markers; each occurrence is one program.
    """
    programs = []
    pos = 0
    while True:
        idx = data.find(BLOCK_MARKER, pos)
        if idx < 0:
            break

        name = _read_utf16_name(data, idx + 4)

        # Source marker is within 64 bytes after the name field
        src_marker_search_start = idx + 4 + NAME_SIZE
        src_marker_search_end   = src_marker_search_start + 64
        sm = data.find(SOURCE_MARKER, src_marker_search_start, src_marker_search_end)
        if sm < 0:
            pos = idx + 4
            continue

        text_start = sm + 2  # skip 9b 00
        if data[text_start:text_start + 2] == SOURCE_PREFIX:
            text_start += 2  # skip c0 00 HP PPL version tag

        null_at = _find_null_end(data, text_start)
        source  = data[text_start:null_at].decode('utf-16-le', errors='replace')

        programs.append((name, source))
        pos = idx + 4

    return programs


def write_project_file(output_dir: Path, hpprgm_name: str, program_names: list[str]) -> Path:
    """
    Write a project definition file (.json) to output_dir.
    Returns the path of the written file.
    """
    project = {
        'output':   hpprgm_name,
        'programs': [f'{n}.ppl' for n in program_names],
    }
    project_path = output_dir / (Path(hpprgm_name).stem + '.json')
    project_path.write_text(json.dumps(project, indent=2) + '\n', encoding='utf-8')
    return project_path


def decompile(input_path: Path, output_dir: Path) -> None:
    data     = input_path.read_bytes()
    programs = extract_programs(data)

    if not programs:
        print(f'WARN  No program blocks found in {input_path}', file=sys.stderr)
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for name, source in programs:
        safe_name = re.sub(r'[^\w]', '_', name) or 'program'
        out = output_dir / f'{safe_name}.ppl'
        out.write_text(source.strip() + '\n', encoding='utf-8')
        print(f'OK    {out}  ({len(source)} chars)')
        names.append(safe_name)

    proj = write_project_file(output_dir, input_path.name, names)
    print(f'OK    {proj}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Decompile .hpprgm to .ppl source files')
    parser.add_argument('input',      type=Path, help='Input .hpprgm file')
    parser.add_argument('output_dir', type=Path, help='Output directory for .ppl files')
    args = parser.parse_args()

    if not args.input.exists():
        print(f'ERR   File not found: {args.input}', file=sys.stderr)
        sys.exit(1)

    decompile(args.input, args.output_dir)


if __name__ == '__main__':
    main()
