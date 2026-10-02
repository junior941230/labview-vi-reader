"""Summarize a LabVIEW VI/CTL as readable Markdown.

Extracts the file with pylabview (next to this script), then reports:
version, description, front panel controls, block diagram nodes and wires,
constants, comments and dependencies.

Usage: python vi_summary.py <file.vi> [--keep DIR]
  --keep DIR   keep the full pylabview XML extraction in DIR for deeper digging
"""
import os, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

STRUCTS = {
    'whileLoop': 'While Loop', 'forLoop': 'For Loop', 'select': 'Case Structure',
    'seq': 'Stacked Sequence', 'flatSequence': 'Flat Sequence', 'eventStruct': 'Event Structure',
    'timedLoop': 'Timed Loop', 'inPlaceElemStruct': 'In Place Element', 'diagDisable': 'Diagram Disable',
    'condDisable': 'Conditional Disable', 'typeSelect': 'Type Specialization', 'formula': 'Formula Node',
}
CALLS = {'iUse', 'polyIUse', 'dynIUse', 'callParentDynIUse', 'xIUse', 'callByRef', 'overridableParentIUse',
         'dynLink', 'staticVIRef'}
DDO = {'stdNum': 'numeric', 'stdBool': 'boolean', 'stdString': 'string', 'stdPath': 'path',
       'stdClust': 'cluster', 'indArr': 'array', 'stdGraph': 'chart/graph', 'stdRing': 'ring',
       'stdMenuRing': 'enum/ring', 'stdRefNum': 'refnum', 'stdLvVariant': 'variant',
       'stdTag': 'I/O name', 'stdTable': 'table', 'stdListbox': 'listbox', 'stdCont': 'container',
       'stdColorNum': 'color box', 'stdKnob': 'knob/slider', 'stdTime': 'timestamp',
       'stdComboBox': 'combo box', 'stdLvClass': 'LV object', 'stdPict': 'picture'}


def extract(vi, out):
    xml = os.path.join(out, 'vi.xml')
    r = subprocess.run([sys.executable, '-W', 'ignore', '-m', 'pylabview.readRSRC', '-x', '-i', vi, '-m', xml],
                       cwd=HERE, capture_output=True, text=True, errors='replace')
    if r.returncode or not os.path.exists(xml):
        sys.exit('pylabview failed:\n' + r.stderr[-2000:])
    warn = [l.split(': ', 1)[-1] for l in r.stderr.splitlines() if 'Warning' in l or 'failed' in l]
    return xml, warn


def text_of(el):
    """Label/comment text: first <text> under el, quotes stripped."""
    t = el.find('.//textRec/text') if el is not None else None
    if t is None or t.text is None:
        return ''
    s = t.text.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def own_label(el):
    """Label part (partID 16) of a ddo / node, or its <label> child."""
    for part in el.iterfind('./partsList/SL__arrayElement'):
        if part.get('class') == 'label':
            return text_of(part)
    lab = el.find('./label')
    return text_of(lab) if lab is not None else ''


def const_value(dco):
    v = dco.findtext('ConstValue')
    if not v:
        return '?'
    b = bytes.fromhex(v) if re.fullmatch(r'[0-9A-Fa-f]*', v) and len(v) % 2 == 0 else None
    if b is None:
        return v[:60]
    if len(b) >= 4 and int.from_bytes(b[:4], 'big') == len(b) - 4:  # string-like: u32 length + bytes
        s = b[4:].decode('latin1')
        if s.isprintable():
            return repr(s)
    if len(b) <= 8:
        return '{} (0x{})'.format(int.from_bytes(b, 'big', signed=True), v)
    return '0x' + v[:64] + ('...' if len(v) > 64 else '')


def heap(path):
    return ET.parse(path).getroot() if os.path.exists(path) else None


def first(*xs):
    return next((x for x in xs if x is not None), None)


def summarize(vi, keep=None):
    out = keep or tempfile.mkdtemp(prefix='visum_')
    os.makedirs(out, exist_ok=True)
    xml, warn = extract(vi, out)
    root = ET.parse(xml).getroot()
    base = os.path.splitext(xml)[0]
    L = []
    w = L.append

    w('# ' + os.path.basename(vi))
    vers = root.find('.//vers/Section/Version')
    if vers is not None:
        w('Saved in LabVIEW version: ' + vers.get('Info', ''))
    desc = root.find('.//STRG/Section/String')
    if desc is not None and (desc.text or '').strip():
        w('\n## Description\n' + desc.text.strip())

    # Front panel
    fp = first(heap(base + '_FPHb.xml'), heap(base + '_FPHc.xml'))
    fp_names = {}
    if fp is not None:
        w('\n## Front panel')
        for d in fp.iter('SL__arrayElement'):
            if d.get('class') != 'fPDCO':
                continue
            ddo = d.find('ddo')
            kind = DDO.get(ddo.get('class'), ddo.get('class')) if ddo is not None else '?'
            name = own_label(ddo) if ddo is not None else ''
            fp_names[d.get('uid')] = name or kind
            w('- "{}" ({})'.format(name, kind))

    # Block diagram
    bd = first(heap(base + '_BDHb.xml'), heap(base + '_BDHc.xml'))
    if bd is not None:
        w('\n## Block diagram')
        parent = {c: p for p in bd.iter() for c in p}
        nodes = {}   # uid -> description
        term_owner = {}

        def describe(el):
            cls = el.get('class')
            uid = el.get('uid')
            lab = own_label(el)
            if cls in STRUCTS:
                return '{}#{}'.format(STRUCTS[cls], uid)
            if cls == 'prim':
                return 'prim(resID {})#{}'.format(el.findtext('primResID'), uid)
            if cls in CALLS:
                return 'subVI call ({}){}#{}'.format(cls, ' "' + lab + '"' if lab else '', uid)
            return '{}{}#{}'.format(cls, ' "' + lab + '"' if lab else '', uid)

        # terminals -> owning node
        for t in bd.iter('SL__arrayElement'):
            cls = t.get('class')
            if cls is None or t.find('dco') is None:
                continue
            dco = t.find('dco')
            uid = t.get('uid')
            if cls == 'fPTerm':
                term_owner[uid] = 'FP "{}"'.format(fp_names.get(dco.get('uid'), '?'))
                continue
            if dco.get('class') == 'bDConstDCO':
                ddo = dco.find('ddo')
                nm = own_label(ddo) if ddo is not None else ''
                term_owner[uid] = 'const {}{}'.format(const_value(dco), ' "' + nm + '"' if nm else '')
                continue
            # walk up to the node that owns this terminal (skip termList)
            p = parent.get(t)
            while p is not None and not (p.tag == 'SL__arrayElement' and p.get('class')
                                         and p.find('termList') is not None and t in p.find('termList')):
                p = parent.get(p)
            if p is not None:
                desc = describe(p)
                if p.get('class') == 'sRN':  # diagram's own terminal set, use the term kind instead
                    desc = '{}#{}'.format(cls, uid)
                elif cls not in ('term', 'parm'):
                    desc += '.' + cls
                pi = list(p.find('termList')).index(t)
                term_owner[uid] = '{}[t{}]'.format(desc, pi)

        # tunnels: a dco with its own termList joins outer and inner terminals
        for t in bd.iter('SL__arrayElement'):
            dco = t.find('dco')
            if dco is None or dco.find('termList') is None:
                continue
            owner = term_owner.get(t.get('uid'), '?').rsplit('[', 1)[0]
            for x in dco.iterfind('./termList/SL__arrayElement'):
                term_owner[x.get('uid')] = '{} {}#{}'.format(owner, dco.get('class'), dco.get('uid'))

        def walk(el, depth):
            for dl in el.iterfind('./diagramList/SL__arrayElement'):
                if len(el.findall('./diagramList/SL__arrayElement')) > 1:
                    w('  ' * depth + '- (frame/case)')
                walk_diag(dl, depth + 1)

        def walk_diag(diag, depth):
            for n in diag.iterfind('./zPlaneList/SL__arrayElement'):
                cls = n.get('class')
                if cls is None or cls in ('attachment', 'sRN'):
                    continue
                if cls == 'label':
                    w('  ' * depth + '- comment: "{}"'.format(text_of(n)))
                    continue
                w('  ' * depth + '- ' + describe(n))
                if n.find('diagramList') is not None:
                    walk(n, depth + 1)
            for s in diag.iterfind('./signalList/SL__arrayElement'):
                ts = [x.get('uid') for x in s.iterfind('./termList/SL__arrayElement')]
                if ts:
                    names = [term_owner.get(u, 'term#' + u) for u in ts]
                    w('  ' * depth + '  wire: {} -> {}'.format(names[0], ', '.join(names[1:])))

        top = bd.find('.//root')
        if top is not None:
            walk_diag(top, 0)

    # Dependencies
    deps = []
    for blk in ('LIvi', 'LIfp', 'LIbd'):
        for obj in root.iterfind('.//{}/Section/*/*'.format(blk)):
            path = [s.text or '' for s in obj.iterfind('./LinkSavePathRef/String')]
            if path:
                deps.append('{} {}'.format(obj.tag, re.sub(r'&#x[0-9A-Fa-f]+;', '', '/'.join(path))))
    if deps:
        w('\n## Dependencies (link objects)')
        for d in dict.fromkeys(deps):
            w('- ' + d)

    if warn:
        w('\n## Parser notes')
        for x in warn:
            w('- ' + x)
    w('\n(prim resIDs are LabVIEW internal function IDs; names are not stored in the file. '
      'Full XML: {})'.format(out if keep else 'rerun with --keep DIR'))
    return '\n'.join(L)


if __name__ == '__main__':
    args = sys.argv[1:]
    keep = None
    if '--keep' in args:
        i = args.index('--keep'); keep = args[i + 1]; del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding='utf-8')
    print(summarize(args[0], keep))
