---
type: reference
status: current
covers:
  - path:infrastructure/base/security/honeypots/honeyfs
bluf: "Real contents for fs.pickle nodes that ship as zero-byte files."
claims:
  - id: honeyfs-attaches-only-to-existing-nodes
    says: init_honeyfs sets A_REALFILE on nodes already in fs.pickle and cannot create new ones
    mode: verified
    at: 2026-09-20
    j: "python3 -c 'load fs.pickle; assert /etc/machine-id not in nodes' inside the cowrie pod"
    f: a file placed in honeyfs at a path absent from the pickle becomes readable in a session
    scope:
      - path:infrastructure/base/security/honeypots/honeyfs
  - id: honeyfs-beats-zero-size
    says: file_contents checks A_REALFILE before the zero-size short-circuit, so honeyfs wins
    mode: verified
    at: 2026-09-20
    j: "fs.file_contents('/proc/cpuinfo') returns 4060 B in the running pod"
    f: cowrie reorders file_contents to test A_SIZE first, or drops A_REALFILE
    scope:
      - path:infrastructure/base/security/honeypots/honeyfs
  - id: cowrie-agents-gc-uses-api-key
    says: agents_autodelete reads api_key, so login_password is the ignored key
    mode: superseded
    successor: cowrie-agents-gc-uses-login-password
    j: "cscli config show left AgentsGC.Api nil"
    f: n/a
    scope:
      - path:infrastructure/base/security/crowdsec/helmrelease.yaml
---

# honeyfs — real contents for files the stock pickle leaves EMPTY

`[honeypot] contents_path` points here. At startup `FileSystem.init_honeyfs()` walks this tree
and sets `A_REALFILE` on matching nodes in `fs.pickle`; `file_contents()` checks `A_REALFILE`
FIRST, before the zero-size short-circuit, so a file here wins over an empty pickle entry.

## Why this exists

The stock pickle carries these paths as zero-byte nodes, and `fs.py` returns `b""` for them:

> Zero-byte file lacking A_REALFILE backing: probably empty.
> (The exceptions to this are some system files in /proc and /sys,
> but it's likely better to return nothing than suspiciously fail.)

Upstream chose empty over wrong. For `/proc/cpuinfo` that choice IS the tell: an empty
`/proc/cpuinfo` is impossible on Linux, and the fingerprinting script we see ~590x/week reads
exactly these paths.

## THE RULE: honeyfs can only fill files the pickle ALREADY HAS

`init_honeyfs` attaches to existing nodes. It cannot create them. Verified 2026-09-20 against
our own pickle before writing anything here:

    /proc/cpuinfo        T_FILE   -> attaches
    /proc/version        T_FILE   -> attaches
    /proc/uptime         T_FILE   -> attaches
    /proc/loadavg        T_FILE   -> attaches
    /etc/hostname        T_FILE   -> attaches
    /etc/os-release      T_LINK   -> does NOT attach; the file must live at the symlink TARGET,
                                     which is why os-release is under usr/lib/ here
    /etc/machine-id      absent   -> CANNOT be added this way; needs a rebuilt pickle

Check a path's node type before adding a file, or it will sit here looking authoritative and
do nothing.

## Everything here must agree with everything else

`lscpu` is derived from `/proc/cpuinfo` on real Linux, so a mismatch between them is a
self-refuting contradiction that needs no external reference to detect. Current invariants:

    /proc/cpuinfo   4 processor blocks, Xeon E5-2680 v4, family 6, model 79, stepping 1
    fs-hardening/lscpu   CPU(s): 4, same model name, Model: 79
    fs-hardening/nproc   4
    /proc/version   5.15.0-125-generic  #135-Ubuntu SMP Fri Oct 4 13:27:36 UTC 2024
    cowrie.cfg [shell] kernel_version / kernel_build_string  -- identical pair
    cowrie.cfg [ssh] version  OpenSSH_8.9p1 Ubuntu-3ubuntu0.1  (jammy)
    usr/lib/os-release   Ubuntu 22.04.5 LTS jammy
    /etc/hostname   srv01  == [honeypot] hostname

Change one, change all of them.

## Known limitation: /proc/uptime is STATIC

honeyfs serves fixed bytes, so uptime never advances. An attacker sampling twice hours apart
sees the same value. Still strictly better than empty -- empty is impossible, frozen merely
requires two correlated samples -- but it is not free of tells. A dynamic value needs a code
patch, not config.
