# Self-hosted Chrome extension distribution

## TL;DR

Chrome will not let you install an extension from a file any more. The only way to
ship one to your own machines without publishing to the Web Store is an
**enterprise policy pointing at a self-hosted update manifest**.

- Sign a CRX with a persistent key -> stable extension ID
- Serve `utarr.crx` + `updates.xml` from the cluster as `application/x-chrome-extension`
- Add one `ExtensionInstallForcelist` entry per machine, pointing at the **XML**
- Chrome then installs it, auto-updates it, and shows no developer-mode nag

Worked example: `utarr`, an applet in `@catalyst-swiss-army-knife`.
Host: `infrastructure/base/utarr-dist/` -> `https://utarr-dist.talos00`.

## Why this shape

Three dead ends, so nobody re-tries them:

| Approach | Why it does not work |
|---|---|
| Drag a `.crx` onto `chrome://extensions` | Chrome removed this years ago |
| `--load-extension=<dir>` | **Google Chrome Stable refuses it** — `--load-extension is not allowed in Google Chrome, ignoring`. Chromium still accepts it, which is why dev/verification uses Chromium |
| Self-host a CRX with only `update_url` in the manifest | Chrome ignores updates from non-Web-Store hosts unless policy allows the source |

What remains is enterprise policy. It is well supported and needs no Google account.

## The pieces

### 1. A persistent signing key -> a stable ID

```bash
openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out utarr.pem
chmod 600 utarr.pem
```

The extension ID is derived from the public key, and the policy references that ID.
If the key changes, the ID changes and **every installed policy silently stops
matching**. So the public half is pinned into `manifest.json` as `key`, which makes
the ID stable across rebuilds and machines.

```bash
# public key for manifest.json "key"
openssl rsa -in utarr.pem -pubout -outform DER | base64 | tr -d '\n'

# the extension ID — note 16, NOT 32
openssl rsa -in utarr.pem -pubout -outform DER \
  | openssl dgst -sha256 -binary | head -c 16 | xxd -p -c 16 | tr '0-9a-f' 'a-p'
```

> **`head -c 16`.** The ID is the first **16 bytes** of the digest, hex-expanded to 32
> characters and mapped `0-9a-f` -> `a-p`. Taking 32 bytes yields a 64-character string
> that is not a valid extension ID. This was wrong in the first draft of the utarr plan
> and produced a bogus ID until it was caught.

---

> 🔑 **`utarr.pem` is a secret and is gitignored (`*.pem`).** It is backed up as a
> 1Password document in vault `catalyst-eso` — retrieve with
> `op document get 'utarr extension signing key (rotated 2026-10-30)' --vault catalyst-eso --output utarr.pem`
> (then `chmod 600`). Verify any restore by checksum, never by printing it: an earlier
> rotation here was forced precisely because two lines of key material were echoed to a
> terminal while debugging. Lose it and every
> policy-installed browser needs reinstalling under a new ID. Leak it and someone can
> sign a counterfeit update your machines will accept. Back it up outside the repo —
> 1Password, alongside the app's other credentials.

### 2. The update manifest

```xml
<?xml version='1.0' encoding='UTF-8'?>
<gupdate xmlns='http://www.google.com/update2/response' protocol='2.0'>
  <app appid='mngmmkjkalahaifjgffmgnljjjpeienh'>
    <updatecheck codebase='https://utarr-dist.talos00/utarr.crx' version='1.0.0' />
  </app>
</gupdate>
```

`version` must match `manifest.json`'s version — that comparison is what triggers an
update. `manifest.json` also carries `"update_url"` pointing back at this file.

### 3. The host

A one-pod nginx serving a PVC, behind Traefik on the `*.talos00` cert.

```nginx
types { application/x-chrome-extension crx; }
```

> ⚠️ **The MIME type is the whole thing.** Serving `.crx` as
> `application/octet-stream` makes the install fail with no useful error. If an install
> mysteriously does nothing, check `curl -I` for the content type first.

Two more constraints:

- **No Authentik on this route.** Chrome fetches updates headlessly and cannot complete
  an SSO redirect. `lan-only` is the access control instead.
- **`nginx-unprivileged` on :8080.** The `downloads` namespace enforces restricted
  PodSecurity and stock nginx binds :80 as root.

## Release process

```bash
cd ~/catalyst-devspace/workspace/@catalyst-swiss-army-knife

task package     # build + release/utarr-<version>.zip
task release     # + release/utarr.crx and release/updates.xml, signed with utarr.pem
```

`task release` reads the version from `manifest.json` (not `package.json` — the manifest
version is what Chrome compares), derives the ID from the key, packs the CRX, and
regenerates `updates.xml`.

**To publish**, copy both files into the host's PVC — the NFS share is
`192.168.1.36:/volume1/appdata/downloads/utarr-dist`:

```bash
POD=$(kubectl get pod -n downloads -l app=utarr-dist -o jsonpath='{.items[0].metadata.name}')
kubectl cp release/utarr.crx   downloads/$POD:/usr/share/nginx/html/utarr.crx
kubectl cp release/updates.xml downloads/$POD:/usr/share/nginx/html/updates.xml
```

(If the Synology share is mounted locally, copy straight to it instead.)

**Verify the MIME type before trusting the install:**

```bash
curl -sk -I --resolve utarr-dist.talos00:443:192.168.1.54 \
  https://utarr-dist.talos00/utarr.crx | grep -i content-type
# expect: application/x-chrome-extension
```

### Shipping an update

1. Bump `version` in `manifest.json`
2. `task release`
3. Copy both files up again
4. `chrome://extensions` -> **Update**, or wait for Chrome's own poll

Chrome compares `updates.xml`'s `version` against the installed one. Forgetting the bump
means nothing happens, silently.

## Installing on a machine (macOS, one-time, needs sudo)

```bash
sudo defaults write /Library/Preferences/com.google.Chrome ExtensionInstallForcelist \
  -array "mngmmkjkalahaifjgffmgnljjjpeienh;https://utarr-dist.talos00/updates.xml"
sudo defaults write /Library/Preferences/com.google.Chrome ExtensionInstallSources \
  -array "https://utarr-dist.talos00/*"
```

> The forcelist entry points at the **XML, not the CRX**. Pointing it at the `.crx` is a
> common mistake and fails silently.

Quit Chrome fully, reopen, and check `chrome://policy` — both policies should show OK.
Then `chrome://extensions` should list the extension as managed by policy, with no
"Disable developer mode extensions" bubble.

Debug order when it does not appear:

1. `chrome://policy` — policy missing means the plist did not take
2. policy present but no extension — the update XML or the MIME type is wrong
3. extension present but stale — version in `updates.xml` was not bumped

**Cost of this approach:** policy install is per-machine and needs sudo. There is no MDM
here, so it is not push-button across devices. That is the trade for not publishing.

## Local development

Do **not** use `task dev` to verify anything network-facing: it passes
`--disable-web-security`, which masks cross-origin failures that will happen in a real
browser. Use `task chrome:strict`, which launches Chromium (not Chrome Stable, which
refuses `--load-extension`) without that flag.

---

## Related Issues

<!-- Beads tracking for this doc -->
