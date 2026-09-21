# Copilot delivery runtime contract

Both dependency profiles deliberately select **github-copilot-sdk 1.0.13 with
native runtime 1.0.85 and protocol 3**. The SDK's published default runtime
1.0.83 is not selected. No arbitrary SDK/runtime combination is permitted.

Both API image builds and Hosted preparation explicitly run
`python -m copilot download-runtime --version 1.0.85`, retaining the SDK
downloader's checksum verification. The delivery verifier checks the installed
SDK version, starts the exact packaged executable with authentication disabled,
and checks its actual reported runtime and protocol versions. This check makes
no inference requests. Hosted manifests additionally record this pair and
SHA-256 for every bundled file; archive verification remains exact and fail-closed.
Cold runtime downloading is disabled in deployed processes.

Hosted native working files default to `$HOME/.checkout-recovery-copilot`, not
the potentially read-only source directory. An explicit
`CHECKOUT_COPILOT_STATE_DIRECTORY` overrides that location. PostgreSQL still holds
the durable native archive; this working directory does not authorize remediation.
Hosted source mounting may strip executable permission or prohibit execution.
Startup stages only manifest-listed, SHA-256-verified runtime bytes into an owned
private temporary directory under the state root and restores the four pinned
executables' owner-execute permissions. ZIP permission bits are not trusted. Shutdown
removes that directory; this neither downloads a runtime nor changes its version.

The API image installs the two explicit local packages as non-editable wheels,
independent of development `tool.uv.sources` settings, and checks imports outside
the build checkout. Runtime files remain root-owned but readable/executable by
the non-root service user. Private per-case SDK state uses that user's writable
home, separately from the immutable runtime cache.

## Local and cloud dependency profiles

The laptop profile remains `pyproject.toml` / `uv.lock` / `.venv`, using the
Microsoft mirror as a laptop networking workaround. Its urllib3 2.7.0 is not a
releasable cloud dependency. Do not use laptop validation to approve a cloud
artifact.

Cloud production dependencies are pinned with distribution SHA-256 hashes in
`requirements-cloud.lock`, resolved from public PyPI with stable urllib3 >=2.8.0.
`requirements-cloud-dev.lock` adds pinned tests/build tools while constraining
every production dependency to exactly that production lock.
`dependency-profiles.json` records canonical input hashes, lock hashes, public
index, native runtime pair, and local/cloud version differences.
There is one application implementation, not a copied cloud application.

Use uv 0.11.2 and Python 3.13. From the lane root:

```bash
# Install existing hashes without modifying the local lock or .venv.
python3 scripts/cloud_dependencies.py sync
.venv-cloud/bin/python scripts/cloud_dependencies.py verify --installed
.venv-cloud/bin/python scripts/with_local_db.py -- \
  .venv-cloud/bin/python -m pytest backend/tests --basetemp=.artifacts/cloud-tests
.venv-cloud/bin/python scripts/prepare_hosted.py --with-runtime
.venv-cloud/bin/python scripts/verify_hosted_package.py --require-runtime
```

Only when intentionally updating cloud dependencies, run
`python3 scripts/cloud_dependencies.py lock`, review the lock/difference changes,
then repeat cloud sync and all validation. This derives inputs from the canonical
lane/shared pyprojects, not from the mirror's already-resolved transitive set.
The SDK stays 1.0.13; the runtime stays explicitly 1.0.85/protocol 3.

The API Dockerfile installs hashed cloud pins from public PyPI, builds the two
local wheels without unpinned build isolation, and excludes test/build tooling
from the final runtime. Hosted `requirements.txt` is a byte-for-byte copy of the
cloud production lock. Packaging, ZIP, installed-environment and release guards
fail closed on outdated urllib3 or mismatched pins. The azd prepackage hook
requires an already-synced `.venv-cloud`; it never implicitly runs local `uv run`.
Run release helpers with `.venv-cloud/bin/python scripts/release.py ...` as well.

If corporate Docker networking blocks public PyPI, build the same allowlisted
context with an authorized remote builder; do not downgrade the cloud lock,
disable TLS, or substitute the laptop profile. No mirror override is added to
Hosted remote dependency resolution.
Use only a hash-verified repository-shaped allowlisted build context, never the
whole working repository. Include both cloud locks alongside the Dockerfile's
canonical source and verifier inputs. No `.venv-cloud`, local state or credentials
belong in an uploaded context.

Each changed cloud lock requires fresh tests and release acceptance. Existing
laptop and SDK-trial receipts remain historical evidence, not acceptance of the
cloud set. Cloud-profile validation receipts belong under `.acceptance/cloud-profile/`.
