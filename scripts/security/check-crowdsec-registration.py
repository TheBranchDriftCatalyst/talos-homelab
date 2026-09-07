#!/usr/bin/env python3
"""Exercise the rendered init scripts with a fake LAPI; no cluster changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import yaml

root = Path(__file__).resolve().parents[2]
release = yaml.safe_load((root / 'infrastructure/base/crowdsec/helmrelease.yaml').read_text())
for patch in release['spec']['postRenderers'][0]['kustomize']['patches']:
    script = yaml.safe_load(patch['patch'])['spec']['template']['spec']['initContainers'][0]['command'][2]
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        for name in ['bin', 'stage', 'etc', 'tmp_config']:
            (work / name).mkdir()
        (work / 'uuid').write_text('test-boot-uuid\n')
        fake = {
            'nc': 'exit 0',
            'cscli': '''case "$*" in
*register*) echo register >> "$AUDIT_CALLS"; echo credential > "$AUDIT_CREDS";;
*status*) test -s "$AUDIT_CREDS" && test ! -f "$AUDIT_INVALID";;
esac''',
        }
        for name, body in fake.items():
            executable = work / 'bin' / name
            executable.write_text('#!/bin/sh\n' + body + '\n')
            executable.chmod(0o755)
        adapted = (script.replace('/staging/etc/crowdsec', str(work / 'stage'))
                   .replace('/etc/crowdsec', str(work / 'etc/crowdsec'))
                   .replace('/tmp_config', str(work / 'tmp_config'))
                   .replace('/proc/sys/kernel/random/uuid', str(work / 'uuid')))
        env = dict(os.environ, PATH=str(work / 'bin') + ':' + os.environ['PATH'],
                   LAPI_HOST='test', LAPI_PORT='8080', LAPI_URL='http://test',
                   REGISTRATION_TOKEN='test', USERNAME='test', AUDIT_CALLS=str(work / 'calls'),
                   AUDIT_CREDS=str(work / 'etc/crowdsec/local_api_credentials.yaml'),
                   AUDIT_INVALID=str(work / 'invalid'))
        def boot():
            link = work / 'etc/crowdsec'
            if link.is_symlink():
                link.unlink()
            subprocess.run(['sh', '-c', adapted], env=env, check=True, capture_output=True)
        boot()
        boot()
        assert (work / 'calls').read_text().splitlines() == ['register'], 'reboot registered twice'
        (work / 'invalid').touch()
        boot()
        assert (work / 'calls').read_text().splitlines() == ['register', 'register'], 'invalid credentials did not recover'
        print('PASS first registration, reboot reuse, invalid credential recovery:', patch['target']['name'])
