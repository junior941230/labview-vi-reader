"""Regression run over VIs shipped with LabVIEW 2026.

For each sampled VI: extract to XML, rebuild from XML, compare blocks (decompressed).
Prints warnings bucketed by kind, and round-trip failures by block.

Usage: python tests/corpus_lv2026.py [count] [seed] [lv_root]
"""
import collections, os, random, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blockdiff

count = int(sys.argv[1]) if len(sys.argv) > 1 else 200
seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
root = sys.argv[3] if len(sys.argv) > 3 else r"C:\Program Files (x86)\National Instruments\LabVIEW 2026"
work = os.path.join(tempfile.gettempdir(), "lvcorpus")

files = []
for sub in ("examples", "vi.lib"):
    for dp, _, fs in os.walk(os.path.join(root, sub)):
        files += [os.path.join(dp, f) for f in fs if f.lower().endswith(('.vi', '.ctl', '.vit'))]
random.seed(seed)
files = random.sample(files, min(count, len(files)))

def readrsrc(*args):
    return subprocess.run([sys.executable, "-W", "ignore", "-m", "pylabview.readRSRC", *args],
                          cwd=os.path.dirname(HERE), capture_output=True, text=True, errors="replace")

def run(i_f):
    i, f = i_f
    out = os.path.join(work, str(i)); os.makedirs(out, exist_ok=True)
    xml, vi = os.path.join(out, "x.xml"), os.path.join(out, "x.vi")
    r = readrsrc("-x", "-i", f, "-m", xml)
    msgs = [l for l in r.stderr.splitlines() if l.strip()]
    if r.returncode:
        return f, msgs[-1:] + ["CRASH extract"], None
    r = readrsrc("-c", "-m", xml, "-i", vi)
    if r.returncode:
        return f, msgs + ["CRASH rebuild: " + (r.stderr.strip().splitlines() or [""])[-1]], None
    A, B = blockdiff.blocks(f), blockdiff.blocks(vi)
    return f, msgs, [k[0] for k in sorted(set(A) | set(B)) if A.get(k) != B.get(k)]

cats, ex, rt = collections.Counter(), {}, collections.Counter()
clean = 0
with ThreadPoolExecutor(os.cpu_count()) as p:
    for f, msgs, bad in p.map(run, enumerate(files)):
        for l in msgs:
            k = re.sub(r"^.*?\.(vi|ctl|vit): ", "", l, flags=re.I)
            k = re.sub(r"0x[0-9A-Fa-f]+|\d+", "N", k)[:160]
            cats[k] += 1; ex.setdefault(k, f)
        for b in bad or []:
            rt[b] += 1; ex.setdefault("RT " + b, f)
        clean += not msgs and bad == []
print(f"{len(files)} files, {clean} fully clean (no warnings, identical round-trip)")
print("\n== warnings ==")
for k, n in cats.most_common(30):
    print(f"{n:4} {k}\n       e.g. {ex[k]}")
print("\n== round-trip mismatches by block ==")
for k, n in rt.most_common():
    print(f"{n:4} {k}   e.g. {ex['RT ' + k]}")
