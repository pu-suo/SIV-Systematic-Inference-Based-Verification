# Phase 0 — Revert and capture, notes

## v1-final selection

**Final `v1-final` sha:** `4f5667e` ("removed unnecessary features")

**Originally considered:** `5266902` ("added nl to generation process") — HEAD of `main` at the time Phase 0 began.

**Why `5266902` was excluded:** its own change added the extraction's `nl` field into the generator's LLM payload (user_content), which violates the nl-hygiene invariant enforced by `tests/test_generator.py::test_generator_does_not_include_nl_in_prompt`. Running `pytest tests/` at `5266902` produces that failure. Phase 0's gate requires a fully green v1 test suite, so the tag had to move to the last commit where the suite is green.

## Bisect trail

| Commit | Subject | `pytest tests/` |
|---|---|---|
| 5266902 | added nl to generation process | **RED** — `test_generator_does_not_include_nl_in_prompt` fails (nl leaks into generator prompt) |
| 4f5667e | removed unnecessary features | **GREEN** — 201 passed |

Only one walk-back step was needed; 4f5667e is the last-green commit.

## Implication for later phases

The `nl`-in-generator change from `5266902` is not carried into v2-from-clean. Phase 2 (extractor) and Phase 3 (contrastive generator) rebuilds must preserve the nl-hygiene property: the generator sees the extraction, not the original NL sentence. The existing test `test_generator_does_not_include_nl_in_prompt` encodes this invariant and should continue to enforce it through the refactor.

## Reproduction

```
git checkout 5266902 && pytest tests/ -q   # red: 1 failed
git checkout 4f5667e && pytest tests/ -q   # green: 201 passed
```
