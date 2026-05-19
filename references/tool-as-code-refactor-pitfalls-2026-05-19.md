# Tool-as-Code Refactor Pitfalls - 2026-05-19

This note records the practical lessons from the SkillSentry Tool-as-Code
lightweight refactor. It is intentionally focused on engineering decisions,
failure modes, and verification habits rather than a line-by-line changelog.

## Goal

The problem was not a lack of features. The problem was that the daily tool
surface had become heavy:

- `sentry_run.py` mixed CLI parsing, profile dispatch, case preparation,
  local reuse, executor/grader orchestration, diagnostics, and text rendering.
- Deterministic contracts were repeated across scripts: case identity,
  artifact paths, BOM JSON reads, required outputs, manifest reuse checks.
- Users could not easily tell which entrypoint was light, which was heavy, and
  why a run had to execute again.
- Runtime needed to get shorter without skipping real executor/grader work.

The target shape was:

```text
light entrypoint
  -> profile runner
  -> deterministic core
  -> heavy execution only when needed
  -> existing artifact/session/report contracts preserved
```

## Non-Negotiable Boundaries

These contracts were frozen during the refactor:

- scoring logic
- gate verdict logic
- CI pipeline order
- exit codes
- GitHub Checks conclusion mapping
- executor/grader artifact directory naming
- `PASS / CONDITIONAL PASS / FAIL`
- `S / A / B / C / D / F`
- `authoritative_pass_rate`
- JSON/text output markers that tests and users rely on

The working rule:

```text
Extract helpers, do not change behavior.
Add compatibility facades before removing old exports.
Commit and push small slices.
Run deterministic verification before trusting the change.
```

## Final Module Shape

After the refactor, `sentry_run.py` is a 26-line entry shell. The behavior moved
into explicit Tool-as-Code modules:

```text
sentry_run.py              # entry shell: UTF-8, sys.path, compat exports, CLI start
sentry_run_cli.py          # CLI parsing and profile dispatch
sentry_run_compat.py       # old sentry_run helper exports
sentry_light_profiles.py   # preflight / lint / plan
sentry_local_profile.py    # local profile orchestration
sentry_local_steps.py      # executor-with / grader-report reuse and rerun
sentry_case_prepare.py     # evals.json preparation and case lint session metadata
sentry_profile_runtime.py  # ProfileTimings / profile_payload / save_json
sentry_run_output.py       # text output rendering
sentry_run_plan.py         # plan / dry-run step descriptions
sentry_profile_state.py    # session init, session reuse resolution, cases resolution
sentry_reuse_core.py       # hashes, manifest, reuse forecast, auto reuse
sentry_artifacts.py        # artifact paths, required outputs, current-case filtering
sentry_case_identity.py    # id / case_id / eval-N / artifact_id rules
sentry_run_summary.py      # run/session/result/timing summary reads
```

The public entrypoint did not change:

```powershell
python scripts\sentry_run.py --skill my-skill --profile lint
python scripts\sentry_run.py --skill my-skill --profile plan
python scripts\sentry_run.py --skill my-skill --profile local --dry-run
python scripts\sentry_run.py --skill my-skill --profile local --reuse-session auto
```

## Pitfalls And Fixes

### 1. Mistaking Entry-Point Weight For Core Algorithm Complexity

The tool felt heavy mostly because the entrypoint had too many responsibilities,
not because the scoring algorithm needed a rewrite. The right first move was to
thin the entrypoint and extract deterministic core modules.

Signal that the entrypoint is too heavy:

```text
One file does CLI + session + cases + executor + grader + diagnostics + output.
```

### 2. Making Runs Faster By Skipping The Real LLM Path

This would have broken the purpose of SkillSentry. The safe split is:

```text
No real LLM needed:
  plan, dry-run, contract lint, artifact checks, manifest reuse checks

Real LLM still needed:
  executor skill execution, semantic grading, analysis, failure diagnosis
```

Runtime improvement must come from reuse:

```text
inputs unchanged + manifest matched + required outputs complete
  -> reuse

inputs changed / artifact missing / manifest invalid / user forced rerun
  -> rerun only the necessary step
```

### 3. Letting `id`, `case_id`, And `eval-N` Drift

Case identity was the first contract to centralize. The current compatibility
rule is:

```text
case.id exists:
  eval_id = id
  artifact_id = id

case.id missing:
  eval_id = eval-N
  artifact_id = eval-N

case.case_id exists but case.id missing:
  logical_id = case_id
  artifact_id remains eval-N
```

Do not change artifact directories just because `case_id` exists. That would
break existing executor/grader output conventions.

### 4. Hand-Building Artifact Paths

Artifact paths must be read through `ArtifactRegistry`. Otherwise stale outputs,
case-id-only records, BOM JSON, and missing-output checks drift across scripts.

Useful API:

```text
ArtifactRegistry.required_outputs("executor-with")
ArtifactRegistry.required_outputs("grader-report")
ArtifactRegistry.response_outputs("with_skill")
ArtifactRegistry.grading_outputs()
ArtifactRegistry.current_grading_files()
```

### 5. Trusting Manifest Without Checking Files

A manifest can say a step was OK even when a response, grading file, or report
was later deleted. Reuse must check both manifest state and required outputs.

Required checks:

```text
manifest loads
step record exists
recorded status is OK
input hash matches
required outputs exist
```

The text output must preserve reuse hints such as:

```text
reuse hints:
Required outputs are missing
missing_outputs=
```

### 6. Making Auto-Reuse A Black Box

`--reuse-session auto` should not merely pick a session. It should explain:

- which session was selected
- which steps can be reused
- which steps must rerun
- why reuse failed when it failed

That is why reuse forecast and reuse summary are first-class payload fields.

### 7. Treating Text Output As Non-Contractual

JSON output is an obvious contract, but text output is also user-facing and
test-covered. Preserve markers such as:

```text
reuse:
prepare_cases: reused (matched)
reuse hints:
Required outputs are missing
missing_outputs=
```

Extract rendering into `sentry_run_output.py` before changing any profile logic.

### 8. Breaking Import-Time Compatibility

Tests and external callers may import helpers from `sentry_run`:

```python
import sentry_run
sentry_run.expected_response_outputs(...)
```

Do not remove these exports just because implementation moved. Add a facade:

```python
from sentry_run_compat import *
```

### 9. Doing A Large Rewrite Instead Of Small Slices

The successful sequence was:

```text
extract identity -> verify -> commit -> push
extract artifacts -> verify -> commit -> push
extract output -> verify -> commit -> push
extract profile runner -> verify -> commit -> push
extract CLI -> verify -> commit -> push
extract compatibility facade -> verify -> commit -> push
```

Small commits made it easy to know which slice introduced a problem.

### 10. Cleaning Unrelated Encoding Or Documentation While Refactoring

Some historical docs display mojibake in terminals. Do not fix that during a
behavior-preserving refactor. Encoding cleanup creates large diffs and hides the
actual behavioral risk.

Rule:

```text
Contract-related code: change it.
Planning or new guide: add a focused section/file.
Unrelated historical doc encoding: leave it alone.
```

## Verification Recipe

Minimum check:

```powershell
python -m py_compile scripts\<new_module>.py scripts\sentry_run.py scripts\verify_sentry_run.py
python scripts\verify_sentry_run.py --format json
git diff --check
```

Full deterministic regression:

```powershell
python scripts\verify_sentry_run.py --format json
python scripts\sentry_contract_lint.py --strict --format text
python scripts\verify_sentry_timing.py --format json
python scripts\verify_ci_diagnostics.py --format json
python scripts\verify_ci_exit_contract.py --format json
python scripts\verify_ci_modes.py --format json
python scripts\verify_ci_checks_integration.py --format json
python scripts\verify_sentry_report.py --format json
git diff --check
```

What each check protects:

```text
verify_sentry_run.py
  local profile, reuse, dry-run, plan, force executor/grader, missing outputs

sentry_contract_lint.py
  core contract drift

verify_sentry_timing.py
  timing summary reads and legacy artifact compatibility

verify_ci_diagnostics.py
  diagnostics behavior under missing/abnormal artifacts

verify_ci_exit_contract.py
  exit code contract

verify_ci_modes.py
  mode-specific pipeline order

verify_ci_checks_integration.py
  GitHub Checks mapping

verify_sentry_report.py
  report generation and report artifact reads
```

## Commit Sequence

Key commits in this refactor path:

```text
c81e8a5 refactor: share case identity parsing
098ca9a refactor: share timing artifact access
2f50a96 refactor: share required artifact paths
13d547b refactor: share run summary loading
9f39c8c feat: add lightweight run planning
0de920a feat: auto-select reusable local sessions
f405b1c refactor: extract run planning helpers
d1713a9 refactor: extract local reuse core
725dd69 refactor: extract profile state helpers
bcd4302 refactor: extract run output rendering
9876568 refactor: share profile runtime helpers
0176302 refactor: extract case preparation helper
08483ee refactor: extract delegated ci profile
65804cb refactor: extract debug profile runner
5971f0f refactor: extract light profile runners
61ac337 refactor: extract local reusable steps
b334dcc refactor: extract local profile runner
757e15b refactor: share profile json writer
a51fab1 refactor: extract run cli dispatcher
1e458f2 refactor: extract run compatibility facade
0fbd4a1 docs: add tool-as-code refactor pitfall guide
2b3e2d6 docs: move runtime routing details to reference
76e21be docs: clarify evaluation entrypoints
c631374 feat: summarize run plan weight
```

## Follow-up Closure

After the initial guide was written, three small closure slices finished the
user-facing side of the refactor:

- `SKILL.md` became a router again. Detailed runtime routing moved to
  `references/runtime-router-guide.md`, while the main skill file keeps only the
  trigger, routing rules, core contracts, and forbidden changes.
- `README.md` gained an entrypoint choice table, so users can distinguish local
  light checks, local reusable runs, and full CI/release gates before reading the
  longer profile reference.
- `plan` and `local --dry-run` now expose `summary` and `cost_level` in the JSON
  payload and render the step count, LLM-heavy count, network count, and dry-run
  guarantee in text output.

The important pattern is that "make the tool feel lighter" is not only a runtime
optimization. It also means users can see the weight of a run before starting it.

## Dogfood Findings

The `obsidian-markdown` dogfood run exposed two practical issues that the
deterministic unit-style regression suite did not fully reveal until a real
Claude CLI run happened:

- Empty `SKILLSENTRY_SESSION_ROOT` must not become `Path(".")`. On Python,
  `Path("")` means the current working directory, which caused local profile
  artifacts to appear inside the repository. The fixed default is
  `~/.claude/data/skill-eval/sessions`, matching preflight and the documented
  data/code separation contract.
- SDK-style model names are not always valid Claude CLI names. The local
  executor uses the Claude CLI, so `claude-sonnet-4-6` is normalized to the CLI
  alias `sonnet` before subprocess execution. This preserves the public default
  while avoiding CLI `Not supported model` failures.

Dogfood result:

```text
skill: obsidian-markdown
cases: 3
exact_match: 9/9
verdict: PASS
grade: S
first local run: about 41.5s
second --reuse-session auto run: all heavy steps reused, profile timing about 38ms
```

The follow-up was to make this repeatable instead of leaving it as a one-off
manual transcript. `scripts/verify_local_dogfood.py` now has two modes:

```text
python scripts/verify_local_dogfood.py --format json
  deterministic fake Claude CLI; safe for routine regression

python scripts/verify_local_dogfood.py --real --format json
  real Claude CLI + real installed skill; useful after local profile changes
```

The fake mode is intentionally not a full quality evaluation. It verifies the
runtime contract that had regressed in dogfood: local profile creates artifacts
outside the repo, executor/grader artifacts exist, the manifest is written, and a
second `--reuse-session auto` run reuses prepared cases, executor, and grader
without invoking Claude again.

The final closure was to add `scripts/verify_deterministic.py` as the aggregate
self-check:

```text
python scripts/verify_deterministic.py --format json
  core checks: contract lint, executor/grader/run/local dogfood, report, timing,
  diagnostics, exit contract, Checks, self-test workflow template, dashboard

python scripts/verify_deterministic.py --full --format json
  core checks plus sentry_run local reuse mutation checks, preflight, case
  feasibility, failure report, and all CI modes
```

Keep historical gate fixtures separate because they depend on archived session
directories that are not available in a clean checkout.

Also keep routine and exhaustive verifier modes separate. `verify_sentry_run.py`
used to run every local reuse edge case in the default core path, making the
aggregate check spend most of its time in repeated local profile subprocesses.
The default now checks help, plan, lint, debug, local dry-run, and delegated CI
JSON. The deeper local reuse mutation matrix runs only under
`verify_sentry_run.py --full`, which `verify_deterministic.py --full` selects
automatically.

## CI Self-Test Split

SkillSentry should keep two different GitHub Actions responsibilities:

- `.github/workflows/skill-eval.yml` evaluates changed user skills and should
  keep using the real SkillSentry CI contract.
- `.github/workflows/skillsentry-self-test.yml` verifies SkillSentry's own
  deterministic regression suite when `scripts/`, `references/`, `README.md`,
  `SKILL.md`, or the workflow itself changes.

Do not put the self-check suite into `skill-eval.yml`. That workflow is the
product path for evaluating user skills, and mixing internal tests into it makes
runtime, permissions, secrets, and failure meaning harder to reason about.

The self-test workflow deliberately avoids real LLM execution:

```text
push/pull_request:
  python scripts/verify_deterministic.py --format json

manual workflow_dispatch with full=true:
  python scripts/verify_deterministic.py --full --format json
```

`scripts/verify_self_test_workflow.py` guards this split. It checks that the
self-test workflow template in `references/workflows/skillsentry-self-test.yml`
calls the deterministic aggregate, includes the intended path triggers, uses
Python 3.11, and does not introduce `--real`, Claude CLI install,
`ANTHROPIC_API_KEY`, or `sentry_ci.py`.

GitHub rejected the first attempt to push the live `.github/workflows/` file
because the current OAuth credential does not have `workflow` scope. Keep the
template in the repository until a maintainer with that scope copies it into
`.github/workflows/skillsentry-self-test.yml`.

## When Continuing

Safe next steps:

- Add sample output snapshots for the documented entrypoints if text output
  starts drifting again.
- Add narrow fixture tests for future extraction slices before changing shared
  contracts.

Avoid for now:

- rewriting gate
- changing scoring conclusion mapping
- changing artifact directories
- changing CI pipeline order
- skipping real executor/grader to gain speed
- broad historical documentation encoding cleanup

## Main Lesson

The reusable improvement method is:

```text
freeze contracts
extract deterministic models
add light entrypoints
add safe reuse
thin the main entrypoint
preserve compatibility facades
verify, commit, push after each slice
```

The end goal is not just fewer lines of code. The goal is a tool that users can
understand quickly, that runs less duplicate work, and that still produces
trustworthy results.
