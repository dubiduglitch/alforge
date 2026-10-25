# Contributing to alforge

Thanks for your interest in contributing!

## Development setup

```bash
git clone https://github.com/dubiduglitch/alforge.git
cd alforge
pipx install --path . --editable
# or: pip install -e ".[test]"
```

## Running tests

```bash
python -m pytest tests/ -v
```

## Code style

- No TODOs, FIXMEs, or dead code in `src/`
- Type hints on all public functions
- Tests for new functionality (see `tests/test_alforge.py` for patterns)
- Keep modules focused (one clear responsibility)

## Versioning

Update all three on user-facing changes:
- `pyproject.toml`
- `src/alforge/__init__.py`
- `debian/changelog` (add entry with `dch -v X.Y.Z-1`)

## Building the .deb

```bash
sudo apt install debhelper dh-python pybuild-plugin-pyproject python3-all python3-setuptools python3-wheel
dpkg-buildpackage -us -uc -b
# .deb written to parent directory
```

## Submitting changes

1. Fork the repo
2. Create a feature branch
3. Make your changes with tests
4. Run full test suite
5. Open a PR with the template filled out

## Reporting issues

Use the issue templates for bugs and feature requests. Include:
- `alforge --version`
- OS / distribution
- Exact command and output
- Expected vs actual behavior