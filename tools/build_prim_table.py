"""Build primResID -> function name table from LabVIEW palette files (*.mnu).

Each palette menu has a CPST block (item names) and a PLM2 block (items in the same
order): u16 count header, then per item u16 id, u16 kind, u32 extra, PStr type, pad to 2.
For type "Function" the id is the primitive's resource ID used as primResID in VIs.

Usage: python tools/build_prim_table.py "C:\\Program Files (x86)\\National Instruments\\LabVIEW 2026" out.json
"""
import json, os, struct, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tests'))
import blockdiff


def plm2_items(d):
    _, count = struct.unpack('>HH', d[:4])
    p, items = 4, []
    for _ in range(count):
        rid, kind, extra = struct.unpack('>HHI', d[p:p + 8])
        n = d[p + 8]
        typ = d[p + 9:p + 9 + n].decode('latin1')
        p += 9 + n
        p += p % 2
        items.append((rid, typ))
    return items


def cpst_names(d):
    count = struct.unpack('>I', d[:4])[0]
    p, out = 4, []
    for _ in range(count):
        n = d[p]
        out.append(d[p + 1:p + 1 + n].decode('mac_roman'))
        p += 1 + n
    return out


def build(lv_root):
    table, conflicts = {}, 0
    for dp, _, fs in os.walk(os.path.join(lv_root, 'menus')):
        for f in fs:
            if not f.endswith('.mnu'):
                continue
            try:
                b = blockdiff.blocks(os.path.join(dp, f))
                plm = next(v for k, v in b.items() if k[0] == 'PLM2')
                cps = next(v for k, v in b.items() if k[0] == 'CPST')
                items, names = plm2_items(plm), cpst_names(cps)
            except Exception:
                continue
            if len(items) != len(names):
                continue
            for (rid, typ), name in zip(items, names):
                if typ == 'Function' and name:
                    conflicts += str(rid) in table and table[str(rid)] != name
                    table.setdefault(str(rid), name)
    return table, conflicts


if __name__ == '__main__':
    table, conflicts = build(sys.argv[1])
    with open(sys.argv[2], 'w', encoding='utf-8') as fh:
        json.dump(dict(sorted(table.items(), key=lambda kv: int(kv[0]))), fh, ensure_ascii=False, indent=0)
    print(len(table), 'functions;', conflicts, 'conflicting names (first kept)')
