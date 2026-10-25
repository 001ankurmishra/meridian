# Phase B dependency advisory review

Review date: 2026-10-26 (Asia/Kolkata). Scope: installed Python 3.11 environment
including UI and development dependencies. Scanner findings are dependency
exposure evidence, not proof of reachable exploitation or comprehensive security.

## Original eight findings, reviewed individually

| Installed dependency / advisory | Upstream issue | Meridian exposure assessment and action |
|---|---|---|
| certifi 2026.7.22 / PYSEC-2026-4320 | [Compromised emSign trust chain](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) | Network package/model downloads can use this CA bundle. Update to 2026.10.19 as recommended by the Python advisory database; rebuild images. |
| filelock 3.32.5 / CVE-2026-112940 | [SQLite lock path and symlink attack](https://github.com/tox-dev/filelock/security/advisories/GHSA-v4x8-3wr5-3wq8) | Requires a writable shared lock directory. Meridian does not directly use ReadWriteLock; transitive model/cache use still warrants patching to 4.2.1. |
| filelock 3.32.5 / CVE-2026-112913 | [Windows SQLite side-file attack](https://github.com/tox-dev/filelock/security/advisories/GHSA-9vhv-jxww-xfm5) | Not the macOS verification or Linux container platform. Patch to 4.2.1 for portable environments; no affected Windows execution was tested. |
| filelock 3.32.5 / CVE-2026-112907 | [Windows soft-lock oplock timeout bypass](https://github.com/tox-dev/filelock/security/advisories/GHSA-567q-5qvw-pf92) | Local Windows preconditions; no direct Meridian SoftFileLock use. Patch to 4.2.1, preserving the locked dependency interface tests. |
| setuptools 84.0.0 / GHSA-xmj3-9gf7-h52w | [Legacy wheel namespace path escape on Windows](https://github.com/pypa/setuptools/security/advisories/GHSA-xmj3-9gf7-h52w) | Build/install exposure with a crafted wheel; no runtime wheel installation route. Patch to 84.1.0. |
| urllib3 2.7.0 / PYSEC-2026-4177 | [Unbounded chunk-size field buffering](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) | Requests/model downloads depend on urllib3; streaming an untrusted server response can consume memory. Patch to 2.8.0. |
| urllib3 2.7.0 / PYSEC-2026-4176 | [Chunked Deflate infinite loop](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g) | Affected streaming decoder is transitive; no Meridian custom decompressor. Patch to 2.8.0 and verify HTTP/UI workflows. |
| urllib3 2.7.0 / PYSEC-2026-4175 | [HTTPS proxy TLS configuration confusion](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77) | Relevant when an operator uses an HTTPS proxy. No custom proxy TLS settings found in Meridian. Patch to 2.8.0; upstream now separates proxy and destination TLS settings. |

## Additional findings in the repeated scan

The current scan reported 45 findings in five packages, including 37 Pillow
findings beyond the original eight. No image upload/decoding workflow exists in
Meridian, but Pillow is installed transitively. Upgrade Pillow 12.3.0 to 13.0.0,
the scanner's fixed version for all 37. See [Pillow release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html).
The exact IDs, aliases and fixed versions are saved in `advisories-before.json`.

Streamlit 1.64.0 requires Pillow <13. Official [PyPI metadata for Streamlit
1.66.1](https://pypi.org/pypi/streamlit/1.66.1/json) permits Pillow >=9.2,<14 and
Python >=3.11. This is the reason for that controlled UI dependency update.
No resolver override ignores compatibility bounds. The target lock change is six
packages, with `httptools` and `toml` removed as no longer required transitive
Streamlit dependencies. The rest of the lock stays fixed.

Verification results are recorded after installation; a successful resolver
alone is not compatibility verification. Model loading, chunk identity, API,
Streamlit states, authenticated workflow and final quality gates must pass.

Verification: targeted lock/sync completed on Python 3.11; full `pytest -q tests`
passed 748 tests (three framework deprecation warnings). `pip-audit --format json`
reported no known vulnerabilities. See `advisories-after.json`. Linux image
validation remains part of deployment verification.
