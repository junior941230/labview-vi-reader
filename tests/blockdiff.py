"""Compare two RSRC files block by block (zlib blocks compared decompressed).

Usage: python blockdiff.py a.vi b.vi
Prints differing blocks; exit code 1 if any differ.
"""
import struct, sys, zlib

def blocks(path):
    d = open(path, 'rb').read()
    _, _, _, _, info_off, _, data_off, _ = struct.unpack('>6sH4s4sIIII', d[:32])
    bl_off, names_off = struct.unpack('>II', d[info_off+44:info_off+52])
    base = info_off + bl_off
    out = {}
    for i in range(struct.unpack('>I', d[base:base+4])[0] + 1):
        ident, cnt, off = struct.unpack('>4sII', d[base+4+i*12:base+16+i*12])
        for j in range(cnt + 1):
            sid, _, _, sec_off, _ = struct.unpack('>iIIII', d[base+off+j*20:base+off+j*20+20])
            p = data_off + sec_off
            raw = d[p+4:p+4+struct.unpack('>I', d[p:p+4])[0]]
            try:  # u32 size + zlib stream
                if raw[4:5] == b'\x78':
                    raw = zlib.decompress(raw[4:])
            except zlib.error:
                pass
            out[(ident.decode('latin1'), sid)] = raw
    return out

def diff(a, b):
    A, B = blocks(a), blocks(b)
    bad = [k for k in sorted(set(A) | set(B)) if A.get(k) != B.get(k)]
    for k in bad:
        x, y = A.get(k, b''), B.get(k, b'')
        at = next((i for i in range(min(len(x), len(y))) if x[i] != y[i]), min(len(x), len(y)))
        print(f'{k[0]}[{k[1]}] differs: len {len(x)} vs {len(y)}, first diff at {at}')
    return bad

if __name__ == '__main__':
    sys.exit(1 if diff(sys.argv[1], sys.argv[2]) else 0)
