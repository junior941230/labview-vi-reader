"""Summarize a LabVIEW VI/CTL as readable Markdown.

Extracts the file with pylabview (next to this script), then reports:
version, description, front panel controls, block diagram nodes and wires,
constants, comments and dependencies.

Usage: python vi_summary.py <file.vi> [--keep DIR] [--textcp CP]
  --keep DIR   keep the full pylabview XML extraction in DIR for deeper digging
  --textcp CP  code page of the VI's text (default: auto, detects Big5/GBK/Shift-JIS,
               else mac_roman)
"""
import json, os, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
# primResID -> function name, built from LabVIEW palette files by tools/build_prim_table.py
try:
    with open(os.path.join(HERE, 'prim_names.json'), encoding='utf-8') as _fh:
        PRIMS = json.load(_fh)
except OSError:
    PRIMS = {}

STRUCTS = {
    'whileLoop': 'While Loop', 'forLoop': 'For Loop', 'select': 'Case Structure',
    'seq': 'Stacked Sequence', 'flatSequence': 'Flat Sequence', 'eventStruct': 'Event Structure',
    'timedLoop': 'Timed Loop', 'timeLoop': 'Timed Loop', 'inPlaceElemStruct': 'In Place Element',
    'diagDisable': 'Diagram Disable', 'commentNode': 'Disable Structure',
    'condDisable': 'Conditional Disable', 'typeSelect': 'Type Specialization', 'formula': 'Formula Node',
    'decomposeRecomposeStructure': 'In Place Element',
}
TEXT_CP = 'latin1'  # code page for string constants / case strings, set by extract()
# Built-in nodes stored with their own class (not as prim); class name is kept next to it
NODES = {
    'aBuild': 'Build Array', 'aIndx': 'Index Array', 'aInit': 'Initialize Array', 'aReplace': 'Replace Array Subset',
    'aInsert': 'Insert Into Array', 'subset': 'Array/String Subset', 'decimate': 'Decimate 1D Array',
    'concat': 'Concatenate Strings', 'printf': 'Format Into String', 'scanf': 'Scan From String',
    'mux': 'Bundle', 'demux': 'Unbundle', 'nMux': 'Bundle/Unbundle By Name', 'mergeErrors': 'Merge Errors',
    'cpdArith': 'Compound Arithmetic', 'propNode': 'Property Node', 'invokeNode': 'Invoke Node',
    'extFunc': 'Call Library Function', 'xNode': 'XNode', 'hiddenFBNode': 'Feedback Node',
    'slaveFBInputNode': 'Feedback Node init', 'sharedVariable': 'Shared Variable', 'eventDataNode': 'Event Data Node',
}
CALLS = {'iUse', 'polyIUse', 'dynIUse', 'callParentDynIUse', 'xIUse', 'callByRef', 'overridableParentIUse',
         'dynLink', 'staticVIRef'}
DDO = {'stdNum': 'numeric', 'stdBool': 'boolean', 'stdString': 'string', 'stdPath': 'path',
       'stdClust': 'cluster', 'indArr': 'array', 'stdGraph': 'chart/graph', 'stdRing': 'ring',
       'stdMenuRing': 'enum/ring', 'stdRefNum': 'refnum', 'stdLvVariant': 'variant',
       'stdTag': 'I/O name', 'stdTable': 'table', 'stdListbox': 'listbox', 'stdCont': 'container',
       'stdColorNum': 'color box', 'stdKnob': 'knob/slider', 'stdTime': 'timestamp',
       'stdComboBox': 'combo box', 'stdLvClass': 'LV object', 'stdPict': 'picture'}


def extract(vi, out, textcp='auto'):
    vi = os.path.abspath(vi)  # pylabview runs from HERE
    xml = os.path.join(out, 'vi.xml')
    r = subprocess.run([sys.executable, '-W', 'ignore', '-m', 'pylabview.readRSRC', '-x', '-i', vi, '-m', xml,
                        '--textcp', 'mac_roman' if textcp == 'auto' else textcp],
                       cwd=HERE, capture_output=True, text=True, errors='replace')
    if r.returncode or not os.path.exists(xml):
        sys.exit('pylabview failed:\n' + r.stderr[-2000:])
    if textcp == 'auto':
        cp = guess_textcp(out)
        if cp:
            for fn in os.listdir(out):  # a block that fails under cp would otherwise leave a stale file
                if os.path.isfile(os.path.join(out, fn)):
                    os.remove(os.path.join(out, fn))
            return extract(vi, out, cp)
    global TEXT_CP
    TEXT_CP = 'latin1' if textcp in ('auto', 'mac_roman') else textcp
    warn = [l.split(': ', 1)[-1] for l in r.stderr.splitlines() if 'Warning' in l or 'failed' in l]
    return xml, warn


def guess_textcp(out):
    """VIs store text in the saving system's ANSI code page, not marked in the file.
    If the non-ASCII label bytes decode cleanly as Big5 / GBK / Shift-JIS, that's it."""
    raw = set()
    for fn in os.listdir(out):
        if fn.endswith('.xml'):
            for el in ET.parse(os.path.join(out, fn)).getroot().iter():
                # only labels/comments; other strings may be binary blobs
                for s in [el.text or '' if el.tag == 'text' else '', el.get('Label') or '']:
                    if any(ord(c) > 127 for c in s) and '&#x' not in s:
                        try:
                            raw.add(s.encode('mac_roman'))
                        except UnicodeEncodeError:
                            pass
    if not raw:
        return None
    def cjk(b, cp):
        try:
            return any(ord(c) > 0x2e7f for c in b.decode(cp))
        except UnicodeDecodeError:
            return False
    for cp in ('cp950', 'gbk', 'cp932'):
        # a stray non-text byte string shouldn't block detection, so 90% is enough
        if sum(cjk(b, cp) for b in raw) >= 0.9 * len(raw):
            return cp
    return None


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
        s = b[4:].decode(TEXT_CP, errors='replace')
        if s.isprintable():
            return repr(s)
    if len(b) == 8:  # often a cluster of two I32 (e.g. IMAQ ranges {lower, upper})
        return '{} (0x{}; as 2x I32: {}, {})'.format(int.from_bytes(b, 'big', signed=True), v,
                                                     int.from_bytes(b[:4], 'big', signed=True),
                                                     int.from_bytes(b[4:], 'big', signed=True))
    if len(b) <= 8:
        return '{} (0x{})'.format(int.from_bytes(b, 'big', signed=True), v)
    return '0x' + v[:64] + ('...' if len(v) > 64 else '')


def heap(path):
    return ET.parse(path).getroot() if os.path.exists(path) else None


def first(*xs):
    return next((x for x in xs if x is not None), None)


def summarize(vi, keep=None, textcp='auto'):
    out = keep or tempfile.mkdtemp(prefix='visum_')
    os.makedirs(out, exist_ok=True)
    xml, warn = extract(vi, out, textcp)
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

    # Type lookup: heap TypeID -> consolidated (DTHP shift) -> flat VCTP entry (TopLevel)
    vctp = root.find('.//VCTP/Section')
    flat = vctp.findall('./TypeDesc') if vctp is not None else []
    top_types = {int(t.get('Index')): int(t.get('FlatTypeID')) for t in vctp.iterfind('./TopLevel/TypeDesc')} if vctp is not None else {}
    sl = root.find('.//DTHP/Section/TypeDescSlice')
    shift = int(sl.get('IndexShift')) if sl is not None else 0

    def heap_type(h):
        f = top_types.get(h + shift - 1)
        td = flat[f] if f is not None and f < len(flat) else None
        while td is not None and td.get('Type') == 'TypeDef':  # unwrap typedef
            td = td.find('./TypeDesc')
        return td

    def instance_name(obj):
        """Express VI instances link as qualified name ["Instance", "N"]; their code is in VINS."""
        q = [s.text or '' for s in obj.iterfind('./LinkSaveQualName/String')]
        return 'Express VI instance ' + q[1] if len(q) == 2 and q[0] == 'Instance' else None

    # Link objects point at heap objects by uid (LinkOffsetList / APILinkCacheList)
    def links(blk):
        out = {}
        for obj in root.iterfind('.//{}/Section/*/*'.format(blk)):
            path = [s.text or '' for s in obj.iterfind('./LinkSavePathRef/String')]
            name = instance_name(obj) or (re.sub(r'&#x[0-9A-Fa-f]+;', '', path[-1]) if path else '')
            for o in obj.iterfind('./*/Offset'):
                out.setdefault(str(int(o.text, 0)), name)
        return out
    fp_links, bd_links = links('LIfp'), links('LIbd')

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
            src = fp_links.get(d.get('uid')) or (fp_links.get(ddo.get('uid')) if ddo is not None else None)
            if src:
                kind += ', ' + src
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
                rid = el.findtext('primResID')
                if rid in PRIMS:
                    return '{} [prim {}]#{}'.format(PRIMS[rid], rid, uid)
                return 'prim(resID {})#{}'.format(rid, uid)
            if cls in CALLS:
                target = bd_links.get(uid) or lab
                return 'subVI call ({}){}#{}'.format(cls, ' "' + target + '"' if target else '', uid)
            name = '{} [{}]'.format(NODES[cls], cls) if cls in NODES else cls
            target = bd_links.get(uid) or lab
            return '{}{}#{}'.format(name, ' "' + target + '"' if target else '', uid)

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
                # subVI terminal name = label of its type, which is the callee's connector control.
                # Not used for prims/built-in nodes: their terminal types follow the wired data,
                # so the label would be the upstream wire's, not the terminal's own name.
                tname = None
                if p.get('class') in CALLS:
                    h = re.sub(r'\D', '', dco.findtext('typeDesc') or '')
                    ttd = heap_type(int(h)) if h else None
                    tname = ttd.get('Label') if ttd is not None else None
                term_owner[uid] = '{}[{}]'.format(desc, tname or 't{}'.format(pi))

        # tunnels: a dco with its own termList joins outer and inner terminals
        for t in bd.iter('SL__arrayElement'):
            dco = t.find('dco')
            if dco is None or dco.find('termList') is None:
                continue
            owner = term_owner.get(t.get('uid'), '?').rsplit('[', 1)[0]
            for x in dco.iterfind('./termList/SL__arrayElement'):
                term_owner[x.get('uid')] = '{} {}#{}'.format(owner, dco.get('class'), dco.get('uid'))

        def walk(el, depth):
            frames = el.findall('./diagramList/SL__arrayElement')
            labels = case_labels(el, len(frames)) if el.get('class') == 'select' else None
            active = el.findtext('activeDiag')  # Disable structures: only this frame runs
            active = int(active, 16) if active and re.fullmatch(r'[0-9A-Fa-f]+', active) else 0
            # activeDiag is omitted when it is 0 (like SelectDefaultCase); frame 0 then runs
            for i, dl in enumerate(frames):
                if labels:
                    w('  ' * depth + '- case ' + labels[i])
                elif el.get('class') == 'commentNode':
                    w('  ' * depth + '- frame {} ({})'.format(i, 'ACTIVE' if i == active else 'disabled, does not run'))
                elif len(frames) > 1:
                    w('  ' * depth + '- frame {}'.format(i))
                walk_diag(dl, depth + 1)

        def case_labels(sel, nframes):
            """Selector values per case frame, from SelectRangeArray32 / SelectStringArray."""
            td = None
            cs = next((d for d in sel.iterfind('./termList/SL__arrayElement/dco') if d.get('class') == 'caseSel'), None)
            if cs is not None and cs.findtext('typeDesc'):
                td = heap_type(int(re.sub(r'\D', '', cs.findtext('typeDesc'))))
            kind = td.get('Type', '') if td is not None else ''
            enum = [e.text or '' for e in td.iterfind('EnumLabel')] if td is not None else []
            strs = [bytes.fromhex(s.text or '').decode(TEXT_CP, errors='replace') for s in sel.iterfind('./SelectStringArray/SL__arrayElement')]

            def val(v):
                if strs:
                    return '"{}"'.format(strs[v]) if 0 <= v < len(strs) else str(v)
                if enum:
                    return '"{}"'.format(enum[v]) if 0 <= v < len(enum) else str(v)
                if kind == 'Boolean':
                    return 'True' if v else 'False'
                if kind == 'Cluster':  # error cluster: codes, with INT_MIN meaning "no error"
                    return 'No Error' if v == -2**31 else 'Error {}'.format(v)
                return str(v)

            out = [[] for _ in range(nframes)]
            for r in sel.iterfind('./SelectRangeArray32/SL__arrayElement'):
                a, b = int(r.findtext('start')), int(r.findtext('end'))
                ta, tb = r.findtext('startRangeType'), r.findtext('endRangeType')
                if kind == 'Cluster' and a == b == -2**31:
                    s = 'No Error'
                elif a == b and ta == tb == '0':
                    s = val(a)
                elif kind == 'Cluster':
                    s = 'Error {}..{}'.format('' if ta == '3' else a, '' if tb == '3' else b)
                else:
                    s = '{}..{}'.format('' if ta == '3' else val(a), '' if tb == '3' else val(b))
                i = int(r.findtext('diagramIdx'))
                if 0 <= i < nframes:
                    out[i].append(s)
            if kind == 'Cluster' and {v for x in out for v in x} <= {'Error 0', 'Error 1'}:
                # plain No Error/Error case: 0/1 is the status, not an error code
                out = [[{'Error 0': 'No Error', 'Error 1': 'Error'}[v] for v in x] for x in out]
            dflt = sel.findtext('SelectDefaultCase')
            if dflt and re.fullmatch(r'[0-9A-Fa-f]+', dflt) and int(dflt, 16) < nframes:
                out[int(dflt, 16)].append('Default')
            # every non-default case has a value; SelectDefaultCase is omitted when it is 0
            return [', '.join(x) or 'Default' for x in out]

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
                # Flat Sequence: frames are sequenceFrame nodes, each with its own diagramList
                for i, f in enumerate(n.iterfind('./sequenceList/SL__arrayElement')):
                    w('  ' * (depth + 1) + '- frame {}'.format(i))
                    walk(f, depth + 2)
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
                deps.append('{} {}'.format(obj.tag, instance_name(obj) or
                                           re.sub(r'&#x[0-9A-Fa-f]+;', '', '/'.join(path))))
    if deps:
        w('\n## Dependencies (link objects)')
        for d in dict.fromkeys(deps):
            w('- ' + d)

    # Express VI instances (e.g. Vision Assistant): each is a whole VI embedded in a VINS section.
    # Section 0 = index: u32 count, then one 256-byte Pascal string (instance name) per section 1..n.
    vins = {int(s.get('Index')): os.path.join(out, s.get('File'))
            for s in root.iterfind('.//VINS/Section') if s.get('File')}
    if 0 in vins and os.path.exists(vins[0]):
        idx = open(vins[0], 'rb').read()
        count = int.from_bytes(idx[:4], 'big')
        names = [idx[5 + 256 * i: 5 + 256 * i + idx[4 + 256 * i]].decode('latin1') for i in range(count)]
        for i, nm in enumerate(names, 1):
            f = vins.get(i)
            if not f or not os.path.exists(f) or open(f, 'rb').read(4) != b'RSRC':
                continue
            sub = os.path.join(out, 'instance_' + nm)
            os.makedirs(sub, exist_ok=True)
            inst_vi = os.path.join(sub, 'instance.vi')
            with open(f, 'rb') as src, open(inst_vi, 'wb') as dst:
                dst.write(src.read())
            try:
                digest = summarize(inst_vi, sub)
            except SystemExit as e:
                digest = '(could not parse: {})'.format(str(e).splitlines()[-1] if str(e) else '?')
            w('\n## Express VI instance {} (embedded code)'.format(nm))
            body = digest.split('\n', 1)[1] if '\n' in digest else digest
            body = body.split('\n(prim(resID N)')[0]  # drop the footer, the outer one covers it
            w(re.sub(r'(?m)^## ', '### ', body.strip()))

    if warn:
        w('\n## Parser notes')
        for x in warn:
            w('- ' + x)
    w('\n(prim(resID N) = built-in function missing from the name table; infer it from context. '
      'Full XML: {})'.format(out if keep else 'rerun with --keep DIR'))
    return '\n'.join(L)


if __name__ == '__main__':
    args = sys.argv[1:]
    keep = None
    if '--keep' in args:
        i = args.index('--keep'); keep = args[i + 1]; del args[i:i + 2]
    textcp = 'auto'
    if '--textcp' in args:
        i = args.index('--textcp'); textcp = args[i + 1]; del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    sys.stdout.reconfigure(encoding='utf-8')
    print(summarize(args[0], keep, textcp))
