# Contributing

Draft; this will be completed during release prep.

- Set up with `uv sync`, then run `uv run pytest` and `uv run ruff check`.
- Only synthetic data goes in this repo. Never commit real usernames, IDs, messages or secrets.
- Install the privacy pre-commit hook once per clone: `ln -s ../../scripts/pre-commit .git/hooks/pre-commit`
- Regenerate fixtures with `uv run python scripts/make_fixtures.py` (add `--check` to verify the committed file is current).
