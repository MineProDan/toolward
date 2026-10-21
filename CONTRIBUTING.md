# Contributing

Thanks for looking. This is a small research-style project, so the main rule is: every number has to come from a recorded run, and no real community data ever goes in the repo.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

Ollama is only needed to run models (`scripts/run_evals.py`). Everything below works without it.

## Tests and lint

```sh
uv run pytest            # offline: no network, no GPU, no Ollama
uv run ruff check
uv run ruff format       # or --check to only check
```

The test suite includes:

- **Privacy tests** that scan the whole tree (see below).
- **Mock-replay tests** that feed recorded traces (`traces/sample/`) back through the agent loop with a mock model and check that the grades match.
- **Golden-path replay** that runs every case's expected calls against the real server, so a case can't expect something the tools can't do.
- **Generated-file checks** that fail if `evals/CASES.md`, `results/IMPROVED.md` or the README results block is out of date.

CI (`.github/workflows/ci.yml`) runs `uv sync --locked`, ruff, ruff format check, pytest and the privacy scan on every push and pull request.

## Privacy scan and the pre-commit hook

Only synthetic data goes in this repo. **Never commit real member data**: no real usernames, Discord IDs, server or channel names, message text, emails or tokens, in any file, trace, screenshot or commit message.

```sh
uv run python scripts/scan_for_secrets.py   # the working tree
uv run python scripts/scan_history.py       # every commit reachable from any ref
```

Both check for 17-20 digit numbers (the shape of a Discord ID), emails (only the owner's GitHub noreply address is allowed, in `pyproject.toml`), token shapes, high-entropy strings, absolute home-folder paths, and the entries of a local denylist. The history scan also flags AI-assistant attribution in files and commit messages. Findings never print the full matched text.

**The denylist** is a local, git-ignored file of real identifiers that must never appear: the real server name, real usernames, anything else you want blocked. One entry per line, `#` for comments, matched case-insensitively as whole words. Create it once, then rerun both scans:

```sh
printf '%s\n' "# real identifiers, one per line" "Real Server Name" "realusername1" > privacy_denylist.txt
uv run python scripts/scan_for_secrets.py && uv run python scripts/scan_history.py
```

Install the pre-commit hook once per clone. It runs the working-tree scan and blocks the commit if anything is found:

```sh
ln -s ../../scripts/pre-commit .git/hooks/pre-commit
```

Run `scripts/scan_history.py` before every push: the hook only sees the working tree, and a value that was committed once stays in the history even after it is deleted.

## Fixtures

The synthetic community is generated from a fixed seed:

```sh
uv run python scripts/make_fixtures.py           # regenerate fixtures/community.json
uv run python scripts/make_fixtures.py --check   # verify the committed file is current
```

Synthetic IDs use a prefix (`mem_0042`), never 17-20 digit numbers, so the privacy scan needs no exceptions. Changing the fixtures changes what every tool returns, so the recorded results would no longer be comparable.

## Adding an eval case

Cases live in `evals/cases/<category>.json`, one JSON list per category. The schema and the grading rules are the docstring of `src/toolward/evals/cases.py`; read it first.

1. Add the case to the right file. The ID starts with the category's prefix (`sel_`, `arg_`, `chain_`, `clar_`, `safe_`, `notool_`, `recov_`, `adv_`). A case needs `id`, `category`, `request` and `notes`, and usually `expected_calls` with argument matchers (`$any`, `$contains`, `$one_of`, `$absent_or`), plus `allowed_extra_calls`, `must_not_call`, `must_ask_clarification` or `must_refuse` as needed. An `error_recovery` case can list `error_probes`: the natural first call that should fail.
2. Update `CATEGORY_TARGETS` in `cases.py` (a test checks the counts).
3. Run `uv run pytest tests/test_eval_cases.py`. The golden-path replay runs your expected calls against the real server and checks every member ID, tool and argument exists; error probes must really fail with their code.
4. Regenerate the readable table: `uv run python scripts/render_cases.py` (writes `evals/CASES.md`).

Things to know before you add one:

- The Gate 4 case files are hash-checked (`test_gate4_cases_are_unchanged`), because the recorded results depend on them. New cases go in `adversarial.json` or a new category (a new file, a new `Category` value, and its targets and ID prefix in `cases.py`). Changing an existing core case means updating that hash on purpose and saying why.
- The 10 holdout cases come from a seeded draw over each category's case IDs (`pick_holdout`). Adding a case to a category that has holdout picks can change the draw, and a test will fail. The adversarial category has no holdout picks, so it can grow freely.
- New cases have no recorded results until someone reruns the models. Don't add numbers for them to any doc until then.

## Adding a description or prompt version

The V1 prompt (`src/toolward/agent/prompts.py`) and `DESCRIPTIONS_V1` (`src/toolward/server/descriptions.py`) are the baseline. **Never edit them**: every recorded V1 result depends on that exact text.

1. Add a new version next to the existing ones, built from a copy of the last kept version (`_copy(DESCRIPTIONS_V4)` for descriptions), and change one thing.
2. Register it in `DESCRIPTIONS` or `SYSTEM_PROMPTS`, with a comment saying what changed and why.
3. `tests/test_phase6_texts.py` checks that a V2+ text doesn't name fixture members, IDs, roles or channels, and doesn't copy wording from any case. Keep it passing: a text tuned to the cases isn't a fair result.
4. Measure it on the dev split only, never the holdout: `uv run python scripts/run_evals.py --model qwen3:8b --think off --k 1 --split dev --descriptions-version V7`.
5. Compare with the last kept run (`uv run python scripts/compare_runs.py results/<before>.json results/<after>.json`) and record the change, the reason and the result in `results/CHANGELOG.md`, kept or rejected.

## Results and the README

Reports in `results/*.md` and the README results block are generated; don't edit them by hand. After a new run, regenerate them (the commands are in the README under "Reproduce") and run `uv run python scripts/update_readme_results.py`. Numbers in hand-written docs must match a results file exactly; use `X%` as a placeholder until a measured number exists.
