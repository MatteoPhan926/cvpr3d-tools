# Contributing

Use Python 3.10+ and run:

```sh
python -m unittest discover -s tests -v
python scripts/check_repository.py
```

Tests use synthetic data and need no network or historical repository. For
packaging changes, follow [the release checks](docs/RELEASING.md). Add regression
tests for malformed inputs, platform differences and reported bugs.

Keep the toolkit small and preserve its offline boundaries. Update the exact
`release-files.json` allowlist when intentionally adding/removing tracked files;
review every new file's ownership and license. Do not import historical assets,
model caches, old experiment scripts or third-party code without a separate
rights and maintenance decision. Use `outputs/` for local reports.

New contributions are under the [MIT scope](LICENSING.md). Keep reviews specific
and constructive. Report Python version, OS, commands and minimal synthetic
reproductions in issues. No response-time commitment is currently published.
