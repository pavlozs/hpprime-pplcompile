import sys, struct
sys.stdout.reconfigure(encoding='utf-8')
data = open(r'C:\Users\pavel\git\hpprime\hpprime-pplcompile\tests\samples\export\geometry.hpprgm', 'rb').read()

def hexdump(d, off, n=64):
    for i in range(off, min(off+n, len(d)), 16):
        row = d[i:i+16]
        h = ' '.join('%02x' % b for b in row)
        a = ''.join(chr(b) if 32<=b<127 else '.' for b in row)
        print('  %04x  %-48s  %s' % (i, h, a))

pat = b'\x8b\x00\x40\x00'
print('=== All 8b 00 40 00 occurrences ===')
i = 0
while True:
    idx = data.find(pat, i)
    if idx < 0:
        break
    name = data[idx+4:idx+4+20].decode('utf-16-le', errors='replace').split('\x00')[0]
    print('  0x%04x: name=%r' % (idx, name))
    hexdump(data, max(0, idx-8), 40)
    i = idx + 2

print()
print('=== 0x00F0 - 0x0155 ===')
hexdump(data, 0x00F0, 100)

print()
print('=== 0x10FE - 0x1165 ===')
hexdump(data, 0x10FE, 100)

# Find all 9b 00 markers
print()
print('=== All 9b 00 markers ===')
pat2 = b'\x9b\x00'
i = 0
while True:
    idx = data.find(pat2, i)
    if idx < 0:
        break
    # Read as UTF-16-LE null-terminated string from idx
    j = idx + 2
    while j + 1 < len(data):
        if data[j] == 0 and data[j+1] == 0:
            break
        j += 2
    raw = data[idx+2:j]
    text = raw.decode('utf-16-le', errors='replace')
    has_export = 'EXPORT' in text
    print('  0x%04x: len=%d chars, has_EXPORT=%s' % (idx, len(text), has_export))
    if has_export:
        print('    preview: %r' % (text[:80],))
    i = idx + 2
