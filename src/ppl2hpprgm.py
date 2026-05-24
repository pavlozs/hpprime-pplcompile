#!/usr/bin/env python3
"""
ppl2hpprgm.py – Compile HP PPL text source (.ppl) to HP Prime binary (.hpprgm)

Multiple .ppl files are bundled into one .hpprgm (each becomes one program block).
The program name inside the block is taken from the filename (without extension).

Usage:
    # From a project definition file
    python src/ppl2hpprgm.py --project geometry.json

    # Explicit file list
    python src/ppl2hpprgm.py -o build/aviation.hpprgm src/nav/NavTas.ppl src/nav/NavWca.ppl ...
"""

import json
import sys
import struct
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# .hpprgm binary format – see hpprgm2ppl.py for detailed layout notes.
#
# Fields marked [?] are present in HP Connectivity Kit output but their exact
# meaning is unknown. Values are taken from a verified sample file.
# ---------------------------------------------------------------------------

# Catalog entry constants
CATALOG_MARKER     = b'\x0b\x02\x40\x00'
NAME_SIZE          = 64   # bytes
CATALOG_ENTRY_SIZE = 4 + NAME_SIZE + 20   # 88 bytes

# Data block constants
BLOCK_MARKER   = b'\x8b\x00\x40\x00'
BLOCK_CONST_44 = struct.pack('<I', 0x00000044)
INNER_HDR_08   = struct.pack('<I', 0x00000008)
INNER_HDR_85   = struct.pack('<I', 0x00800085)
INNER_HDR_00   = struct.pack('<I', 0x00000000)
SOURCE_MARKER  = b'\x9b\x00'
SOURCE_PREFIX  = b'\xc0\x00'

# Global header template (64 bytes) – mostly HP Prime internal VM constants.
# Field 0x30 is computed at compile time (see _build_global_header).
# All other unknown fields are kept identical across all verified exports.
_GLOBAL_HEADER_TEMPLATE = bytes([
    0x7c, 0x61, 0x8a, 0xb2,  # 0x00  magic
    0xfe, 0xff, 0xff, 0xff,  # 0x04  [?]
    0x00, 0x00, 0x00, 0x00,  # 0x08  [?]
    0x08, 0x00, 0x00, 0x00,  # 0x0C  [?]
    0x05, 0xff, 0x7f, 0x00,  # 0x10  [?]
    0x00, 0x00, 0x00, 0x00,  # 0x14
    0x08, 0x00, 0x00, 0x00,  # 0x18  [?]
    0x05, 0xff, 0x3f, 0x02,  # 0x1C  [?]
    0x00, 0x00, 0x00, 0x00,  # 0x20
    0x08, 0x00, 0x00, 0x00,  # 0x24  [?]
    0x05, 0xff, 0xbf, 0x00,  # 0x28  [?]
    0x00, 0x00, 0x00, 0x00,  # 0x2C
    0x00, 0x00, 0x00, 0x00,  # 0x30  computed: N_programs * 88 + 4
    0x3e, 0x02, 0x00, 0x01,  # 0x34  [?]
    0x54, 0x00, 0x00, 0x00,  # 0x38  [?]
    0x44, 0x00, 0x00, 0x00,  # 0x3C  [?]
])
assert len(_GLOBAL_HEADER_TEMPLATE) == 64


def _build_global_header(num_programs: int) -> bytes:
    """Return the 64-byte global header with the computed field at 0x30.

    header[0x30] = N_programs * CATALOG_ENTRY_SIZE + 4
    Verified: geometry (N=2) → 180 (0xB4), aviation (N=5) → 444 (0x1BC).
    """
    hdr = bytearray(_GLOBAL_HEADER_TEMPLATE)
    struct.pack_into('<I', hdr, 0x30, num_programs * CATALOG_ENTRY_SIZE + 4)
    return bytes(hdr)


def load_project(project_path: Path) -> tuple[Path, list[Path]]:
    """
    Load a project definition file (.json) and return (output_path, source_paths).
    All paths in the file are resolved relative to the project file's directory.
    """
    data    = json.loads(project_path.read_text(encoding='utf-8'))
    base    = project_path.parent
    output  = base / data['output']
    sources = [base / p for p in data['programs']]
    return output, sources


def _clean_source(text: str) -> str:
    """Normalise source text for binary encoding.

    - Strip leading whitespace (BOM, blank lines before the first line).
    - Normalise line endings to LF.
    - Ensure exactly one trailing newline (HP Prime exports always end with \\n).
    No pragma is added or removed – the source is stored as written.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text.strip() + '\n'


def _encode_name(name: str) -> bytes:
    """Encode program name as UTF-16-LE, zero-padded to NAME_SIZE bytes."""
    raw = name.encode('utf-16-le')
    if len(raw) + 2 > NAME_SIZE:
        raise ValueError(f'Program name too long (max {NAME_SIZE // 2 - 1} chars): {name!r}')
    return raw + b'\x00\x00' + b'\x00' * (NAME_SIZE - len(raw) - 2)


def _build_catalog_entry(name: str, is_last: bool = False,
                          m3_last: int = 0) -> bytes:
    """
    Build one 88-byte catalog entry (0b 02 40 00 type).

    Metadata layout after name field (20 bytes at +0x44..+0x57):
      +0x44  constant 8              – same for every entry including the first
      +0x48  constant 0x00800205     – catalog entry type/version tag
      +0x4C  constant 57 (0x39)      – [?] purpose unknown
      +0x50  84 (0x54) for non-last  – [?] 84 for every non-last entry
             m3_last for last entry  – formula: len(all_block_bytes) + 4
                                       (verified against geometry.hpprgm and
                                        aviation.hpprgm HP Prime exports)
      +0x54  0x00000044 / 0x014000BE – terminator flag: 0x44 for non-last,
                                       0x014000BE for the last entry
    """
    meta = (
        struct.pack('<I', 0x00000008)  +
        struct.pack('<I', 0x00800205)  +
        struct.pack('<I', 0x00000039)  +
        struct.pack('<I', m3_last      if is_last else 0x00000054) +
        struct.pack('<I', 0x014000BE   if is_last else 0x00000044)
    )
    return CATALOG_MARKER + _encode_name(name) + meta


def _build_program_block(name: str, source: str) -> bytes:
    """
    Build one program data block (8b 00 40 00 type) with embedded source.

    source_payload  = SOURCE_MARKER + SOURCE_PREFIX + source_utf16le + 00 00
    block_data      = BLOCK_CONST_44 + BLOCK_MARKER + name + inner_hdr + source_payload
    output          = uint32(len(block_data)) + block_data
    """
    source_clean   = _clean_source(source)
    source_utf16   = source_clean.encode('utf-16-le')
    source_payload = SOURCE_MARKER + SOURCE_PREFIX + source_utf16 + b'\x00\x00'

    payload_size = struct.pack('<I', len(source_payload))

    block_data = (
        BLOCK_CONST_44      +
        BLOCK_MARKER        +
        _encode_name(name)  +
        INNER_HDR_08        +
        INNER_HDR_85        +
        INNER_HDR_00        +
        payload_size        +
        source_payload
    )
    return struct.pack('<I', len(block_data)) + block_data


def compile_ppl(sources: list[Path], output: Path) -> None:
    entries = []
    for p in sources:
        name   = p.stem
        source = p.read_text(encoding='utf-8')
        entries.append((name, source))

    # Build program blocks first – catalog's last-entry m3 field encodes the
    # total block-section size and must be computed before writing the catalog.
    blocks = b''.join(
        _build_program_block(name, source) for name, source in entries
    )
    m3_last  = len(blocks) + 4   # verified formula from two HP Prime exports
    last_idx = len(entries) - 1
    catalog  = b''.join(
        _build_catalog_entry(name, is_last=(i == last_idx), m3_last=m3_last)
        for i, (name, _) in enumerate(entries)
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_build_global_header(len(entries)) + catalog + blocks)

    total = 64 + len(catalog) + len(blocks)  # 64 = global header size
    print(f'OK    {output}  ({len(entries)} programs, {total} bytes)')


def main() -> None:
    parser = argparse.ArgumentParser(description='Compile .ppl source files to .hpprgm')

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--project', type=Path, metavar='FILE',
                      help='Project definition file (.json)')
    mode.add_argument('-o', '--output', type=Path,
                      help='Output .hpprgm file (use with explicit source list)')

    parser.add_argument('sources', nargs='*', type=Path,
                        help='.ppl source files (required without --project)')
    args = parser.parse_args()

    if args.project:
        if not args.project.exists():
            print(f'ERR   Project file not found: {args.project}', file=sys.stderr)
            sys.exit(1)
        output, sources = load_project(args.project)
    else:
        if not args.sources:
            parser.error('at least one source file is required with -o')
        output  = args.output
        sources = args.sources

    missing = [p for p in sources if not p.exists()]
    if missing:
        for p in missing:
            print(f'ERR   File not found: {p}', file=sys.stderr)
        sys.exit(1)

    compile_ppl(sources, output)


if __name__ == '__main__':
    main()
