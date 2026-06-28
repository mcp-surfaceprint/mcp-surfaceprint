# Contributing

## Development setup

```bash
git clone https://github.com/mcp-surfaceprint/mcp-surfaceprint.git
cd mcp-surfaceprint
uv sync --dev
```

## Running tests

```bash
uv run pytest -q        # quick pass/fail
uv run pytest -v        # verbose output
uv run python tests/show_outputs.py   # visual check against toy servers
```

## Releasing a new version

### 1. Bump the version

Edit `pyproject.toml` and update the `version` field:

```toml
version = "X.Y.Z"
```

Follow [semver](https://semver.org/):
- **Patch** (0.2.0 → 0.2.1): bug fixes only
- **Minor** (0.2.0 → 0.3.0): new features, backward-compatible
- **Major** (0.2.0 → 1.0.0): breaking changes

### 2. Commit and push via PR

```bash
git checkout -b release/vX.Y.Z
git add -A
git commit -m "vX.Y.Z — short description of what changed"
git push -u origin release/vX.Y.Z
```

Open a PR targeting `main` and merge it.

### 3. Tag the release

```bash
git checkout main
git pull
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 4. Create a GitHub Release

Go to [Releases](https://github.com/mcp-surfaceprint/mcp-surfaceprint/releases) → **Draft a new release** → select the `vX.Y.Z` tag → write user-facing release notes (see below).

**Release notes** should be user-facing (not commit-level detail):
- Group by feature, not by file
- Explain the "why" — what users can now do
- Skip internal refactors unless they affect behavior

### 5. Build and publish to PyPI

```bash
rm -rf dist/
uv build
uv publish
```

`uv publish` reads the token from the `UV_PUBLISH_TOKEN` environment variable (set in your environment or CI secrets).

### PyPI token setup (one-time)

1. Generate a token at `https://pypi.org/manage/account/token/` (scoped to `mcp-surfaceprint`)
2. Export it for the current shell session (or store it in CI secrets):

```bash
export UV_PUBLISH_TOKEN="pypi-..."
```

### 6. Verify

```bash
pip install --upgrade mcp-surfaceprint
mcp-surfaceprint --help
```

Check that https://pypi.org/project/mcp-surfaceprint/ shows the new version.
