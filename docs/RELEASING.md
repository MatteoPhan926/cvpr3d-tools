# Release procedure

This candidate has no assumed public remote or PyPI publication. Local success
must not be described as a public CI pass. The first release should be a small
alpha toolkit release; the historical research archive is outside its scope.

## Local gates

From a clean Git checkout with Python 3.10+:

```sh
python -m unittest discover -s tests -v
python scripts/check_repository.py
python -m pip install build==1.2.2.post1
python -m build
python scripts/check_distribution.py dist
```

Use a fresh `dist/` directory per build. Default `python -m build` makes an sdist
and then builds its wheel, so missing source files are exercised. The distribution
checker uses exact path allowlists, compares source/license bytes, checks package
metadata, installs the wheel in a clean temporary virtual environment, exercises
the installed console command and runs tests from the extracted sdist. It never
installs dependencies from the network during these smoke tests. Build tooling
and its initial installation can require network access.

`release-files.json` is the reviewed tracked-file inventory. Updating it is a
publication-scope decision; no recursive archive-directory import is allowed.
`python scripts/check_repository.py --verify-import` additionally checks the
original import receipt; use it for the first snapshot, not after intentional
maintenance changes. The sdist includes synthetic tests and release scripts,
but omits CI-only files. The wheel includes only runtime modules and metadata,
including the license, scope and attribution notices.

## Public gate (requires owner authorization)

1. Confirm the selected new repository name and rights to the exact included
   files. Create an empty repository without an automatically generated README,
   license or fork relationship. Do not use the historical repository as a Git
   template/clone or push its refs.
2. Add that remote to this clean toolkit repository only and push its `main`
   branch explicitly. Never `push --mirror`, `--all`, `--tags` or force-push
   from the historical checkout. No remote or push is configured by export.
3. Verify the public source tree and initial history. Wait for all four
   `Toolkit checks` jobs (Ubuntu/Windows, Python 3.10/3.14), including the sdist
   tests and isolated wheel install, to pass on the exact commit to be released.
4. Confirm the security reporting channel, repository description and support
   scope. Add accurate project URLs to package metadata once the real repository
   exists; any such change requires a fresh public CI run. Configure required
   checks and review rules as appropriate to the maintainer account.
5. Only after a green public commit and explicit release authorization, tag an
   alpha release and attach the audited wheel, sdist and SHA256 checksums built
   from that exact commit. Public CI build logs verify the process; do not claim
   local artifacts were built by CI. Prefer release artifacts built in a reviewed
   CI workflow if adding artifact upload later.
6. PyPI upload is a separate optional action: confirm project-name availability,
   account permissions, version and publishing configuration first. No PyPI
   credentials, uploads, release automation or paid service is required here.

The original CVPR_3D repository remains unchanged remotely. Its historical rights
questions are not solved or enlarged by publishing this isolated toolkit.
