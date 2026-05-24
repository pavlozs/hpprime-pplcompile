# HP Prime .hpprgm Binary Format

Reverse-engineered from HP Connectivity Kit output. Verified against `geometry.hpprgm`.

---

## File Layout

```
[0x00 – 0x3F]   Global header          64 bytes
[0x40 – ...]    Catalog section        N × 88 bytes
[...]           Program data blocks    variable
```

---

## Global Header (64 bytes)

Mostly HP Prime VM constants. Only the magic bytes at `0x00` are confirmed.
All other fields are preserved verbatim from a verified sample.

| Offset | Value             | Notes              |
|--------|-------------------|--------------------|
| 0x00   | `7c 61 8a b2`     | File magic         |
| 0x04   | `fe ff ff ff`     | Unknown            |
| 0x08   | `00 00 00 00`     | Unknown            |
| 0x0C   | `08 00 00 00`     | Unknown            |
| 0x10–0x2F | repeating groups | Unknown VM fields |
| 0x30–0x3F | metadata fields  | Unknown            |

---

## Catalog Entry (88 bytes, marker `0b 02 40 00`)

One entry per program. Stored sequentially after the global header.

```
+0x00   4 bytes    marker  [0b 02 40 00]
+0x04  64 bytes    name    (UTF-16-LE, zero-padded to 64 bytes)
+0x44   4 bytes    [?]     0 for first entry, 8 for subsequent entries
+0x48   4 bytes    [?]     constant 0x00000008
+0x4C   4 bytes    [?]     constant 0x00800205
+0x50   4 bytes    [?]     constant 0x00000039 (57)
+0x54   4 bytes    [?]     unknown offset (may be recomputed by HP Prime on load)
```

---

## Program Data Block (variable size, marker `8b 00 40 00`)

One block per program. Stored sequentially after the catalog.

```
+0x00   4 bytes    block_data_size   (= bytes from +0x04 to end of block)
+0x04   4 bytes    [?]               constant [44 00 00 00]
+0x08   4 bytes    block marker      [8b 00 40 00]
+0x0C  64 bytes    name              (UTF-16-LE, zero-padded)
+0x4C   4 bytes    [?]               constant [08 00 00 00]
+0x50   4 bytes    [?]               constant [85 00 80 00]
+0x54   4 bytes    [?]               constant [00 00 00 00]
+0x58   4 bytes    source_payload_size
+0x5C   2 bytes    source marker     [9b 00]  (U+009B)
+0x5E   2 bytes    source prefix     [c0 00]  (U+00C0, HP PPL version tag)
+0x60   N bytes    source text       (UTF-16-LE, no BOM)
+0x60+N 2 bytes    null terminator   [00 00]
```

### Size formulas

```
source_payload_size = 2 + 2 + len(source_utf16le) + 2
                    = len(source_utf16le) + 6

block_data_size     = 4 + 4 + 64 + 4 + 4 + 4 + 4 + source_payload_size
                    = 88 + source_payload_size
```

---

## Encoding

Source text is stored as **UTF-16-LE without BOM**, null-terminated with `00 00`.

The `c0 00` prefix (U+00C0 = `À`) immediately before the source text is
an HP PPL internal tag. It is stripped on decompile and re-added on compile.

---

## Known Unknowns

- Global header fields `0x08`–`0x3F`: meaning unknown; copied verbatim from sample.
- Catalog field `+0x44`: pattern observed (0 / 8), exact semantics unclear.
- Catalog field `+0x54`: some kind of offset; HP Prime may recompute on load.
- File footer (if any): not present in the tested sample.
