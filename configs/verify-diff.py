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
    # ⚠️ THE LIVE SPEC BECOMES MULTI-DOCUMENT AFTER THE MIGRATION IS APPLIED.
    #
    # talhelper's config carries a separate HostnameConfig document, so once applied the node's
    # own machineconfig spec is a multi-doc stream. yaml.safe_load() raises ComposerError on
    # that — meaning this tool would CRASH at exactly the moment you want to re-run it to prove
    # the apply converged. Use safe_load_all and fold any extra live documents through the same
    # <doc:KIND> path already used for the generated side.
    live=None; live_extra={}
    for d in yaml.safe_load_all(raw):
        if d and "spec" in d:
            sp=d["spec"]
            if isinstance(sp,str):
                docs=[x for x in yaml.safe_load_all(sp) if x]
                live=next((x for x in docs if "machine" in x), docs[0] if docs else {})
                for x in docs:
                    if x is live: continue
                    kind=x.get("kind") or x.get("apiVersion") or "unknown"
                    for k,v in flat(x).items(): live_extra[f"<doc:{kind}>.{k}"]=v
            else:
                live=sp
            break
    # ⚠️ READ EVERY DOCUMENT, not just the v1alpha1 one.
    #
    # talhelper emits a MULTI-DOCUMENT config: the v1alpha1 machine config plus separate
    # documents such as HostnameConfig. An earlier version of this script took only the first
    # document containing "machine" and was therefore blind to the rest — which is exactly
    # where the reboot-causing change lives (talhelper moves hostname into a HostnameConfig
    # document and must remove machine.features.stableHostname, and Talos classifies THAT
    # removal as reboot-required).
    #
    # Non-v1alpha1 documents are surfaced under a synthetic "<doc:KIND>" prefix so they show
    # up in the diff rather than silently not being compared.
    gendocs=[d for d in yaml.safe_load_all(open(f"configs/clusterconfig/catalyst-cluster-{name}.yaml")) if d]
    gen=next((d for d in gendocs if "machine" in d), {})
    extra={}
    for d in gendocs:
        if d is gen: continue
        kind=d.get("kind") or d.get("apiVersion") or "unknown"
        for k,v in flat(d).items(): extra[f"<doc:{kind}>.{k}"]=v
    lf,gf=flat(live or {}),flat(gen or {})
    gf.update(extra)        # generated-side extra documents
    lf.update(live_extra)   # live-side extra documents (present after apply)
    diffs=[]
    for k in sorted(set(lf)|set(gf)):
        a,b=lf.get(k,"<absent>"),gf.get(k,"<absent>")
        if a!=b: diffs.append((k,redact(k,a),redact(k,b)))
    tot+=len(diffs)
    print(f"\n== {name} ==  {len(diffs)} differences  (NOTHING skipped)")
    for k,a,b in diffs:
        print(f"  {k}\n     live: {str(a)[:88]}\n     gen : {str(b)[:88]}")
print(f"\n=== TOTAL ACROSS FLEET: {tot} ===")
