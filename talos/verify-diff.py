import subprocess, yaml, hashlib, re, sys
NODES={"talos00":"192.168.1.54","talos01":"192.168.1.177","talos02-gpu":"192.168.1.144","talos03":"192.168.1.30","talos06":"192.168.1.19"}
# NOTHING IS SKIPPED. Values that look secret are compared by HASH so a change is still
# detected, but the value never reaches the terminal or the transcript.
SECRETY = re.compile(r'(token|secret|\.key$|crt|ca\.|password|Secret)', re.I)
def flat(o,p=""):
    out={}
    if isinstance(o,dict):
        if not o: out[p]="<empty-dict>"
        for k,v in o.items(): out.update(flat(v, f"{p}.{k}" if p else k))
    elif isinstance(o,list):
        if not o: out[p]="<empty-list>"
        for i,v in enumerate(o): out.update(flat(v,f"{p}[{i}]"))
    else: out[p]=o
    return out
def redact(k,v):
    if v in ("<absent>","<empty-list>","<empty-dict>"): return v
    if SECRETY.search(k): return "sha256:"+hashlib.sha256(str(v).encode()).hexdigest()[:12]
    return v
tot=0
for name,ip in NODES.items():
    raw=subprocess.run(["talosctl","-n",ip,"get","machineconfig","-o","yaml"],capture_output=True,text=True,timeout=90).stdout
    live=None
    for d in yaml.safe_load_all(raw):
        if d and "spec" in d:
            s=d["spec"]; live=yaml.safe_load(s) if isinstance(s,str) else s; break
    gen=next(d for d in yaml.safe_load_all(open(f"talos/clusterconfig/catalyst-cluster-{name}.yaml")) if d and "machine" in d)
    lf,gf=flat(live or {}),flat(gen or {})
    diffs=[]
    for k in sorted(set(lf)|set(gf)):
        a,b=lf.get(k,"<absent>"),gf.get(k,"<absent>")
        if a!=b: diffs.append((k,redact(k,a),redact(k,b)))
    tot+=len(diffs)
    print(f"\n== {name} ==  {len(diffs)} differences  (NOTHING skipped)")
    for k,a,b in diffs:
        print(f"  {k}\n     live: {str(a)[:88]}\n     gen : {str(b)[:88]}")
print(f"\n=== TOTAL ACROSS FLEET: {tot} ===")
