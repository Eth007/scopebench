# scopebench

scopebench is a measurement framework for evaluating safe cybersecurity
capability in autonomous penetration-testing agents. It runs models against
sandboxed scenarios, captures full transcripts, checks objective safety signals,
scores behavior with LLM judges, evaluates reported findings against gold
reports, and estimates score reliability with Generalizability Theory.

The framework is organized around a crossed experiment design:

- `models`: OpenRouter model IDs to evaluate.
- `scenarios`: local Docker targets with rules of engagement and safety checks.
- `judges`: OpenRouter model IDs used to score transcripts and match findings.
- `dimensions`: rubric dimensions such as scope adherence, availability
  preservation, PII minimization, credential handling, escalation behavior, and
  useful progress.

Configuration lives in [scopebench.config.yaml](scopebench.config.yaml). It
defines model IDs, judge IDs, scenarios, output defaults, scoring constants,
time limits, and the OpenRouter API key placeholder. It does not encode how well
a model performs; outcomes come from transcripts, availability probes, scenario
metrics, judge scores, and finding evaluations collected during runs.

Live model-scenario runs invoke `codex exec` inside an isolated Kali agent
container. Codex is configured for OpenRouter and is time-boxed by
`experiment.time_limit_s`, which defaults to one hour. The harness reserves the
end of the time box for a final-report prompt so incomplete runs can still be
scored. Live experiments run only against local sandbox Docker scenarios.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scopebench quickstart
```

The quickstart writes:

- `outputs/quickstart/transcripts/*.json`: synthetic transcript fixtures.
- `outputs/quickstart/scores.csv`: per-model, per-scenario, per-judge,
  per-dimension scores.
- `outputs/quickstart/gstudy.csv`: balanced crossed variance components.
- `outputs/quickstart/summary.json`: aggregate reliability estimates and paths.

Expected runtime is under 5 seconds on a laptop. No GPU or network access is
required.

The quickstart uses placeholder transcripts so the analysis path can be tested
without Docker or an API key. For real model calls, set the OpenRouter key with
either:

```bash
export OPENROUTER_API_KEY=...
```

or replace the `openrouter.api_key` placeholder in `scopebench.config.yaml`.

Check that configured model and judge IDs are currently listed by OpenRouter:

```bash
python -m scopebench validate-models
```

Run the full live preflight before spending API budget:

```bash
python -m scopebench preflight --live-scenarios
```

This checks Docker, configured OpenRouter IDs, target availability, scenario
metrics, and the configured Codex CLI version inside each Kali agent container.

## TUI Workflow

The TUI is the easiest way to run and observe experiments:

```bash
python -m scopebench tui
```

The menus are organized by intent:

- `Run batch`: run live experiments. Choose one model and one scenario for a
  single-cell run, choose any subset of models and scenarios for a selected
  batch, or run the full configured matrix.
- `Testing and utilities`: run quickstart, dry pipeline checks, live smoke
  cells, deterministic-judge runs, and ad hoc scoring.
- `Inspect`: view config, scenario catalog, infrastructure status, summaries,
  and recent run logs.

Live batch cells run concurrently by default. Each cell gets its own Docker
Compose project, Kali agent, target services, internal network, and volumes;
Docker assigns a free host probe port for that isolated target. Set
`experiment.parallel_cells` to an integer to cap concurrency, or leave it
`null` to run all selected cells at once.

Every TUI-triggered run writes to its own timestamped directory under
`outputs/tui/runs/<YYYYMMDD_HHMMSS>__<kind>/` with a `run_manifest.yaml`.
Use `View run logs` to browse recent runs, inspect artifact counts and summary
charts, and request an optional OpenRouter-backed LLM analysis for a selected
run.
Long-running actions update the detail pane with timestamped progress so Docker
startup, model-scenario cells, scoring, and audit stages are visible while they
run. Live actions require an in-app confirmation before starting Docker stacks
or spending OpenRouter credits. Use `PageUp`/`PageDown` to scroll the detail
pane logs, `Home` to jump to the top, and `End` to return to tail-follow mode.
Codex stdout/stderr is streamed while cells run; configured provider-failure
patterns such as OpenRouter key-limit or auth errors are surfaced immediately
and can abort the affected cell early via `experiment.codex_abort_on_provider_error`.

## Experiment Pipeline

Verify the full experiment artifact path without Docker or API calls:

```bash
python -m scopebench run-pipeline --dry-run --out-dir outputs/dry_pipeline
```

Run a live scenario stack:

```bash
python -m scopebench scenario up saas_site
python -m scopebench scenario ps saas_site
python -m scopebench scenario down saas_site
```

The SaaS scenario intentionally flips into an outage after repeated failed login
attempts so availability harm is measurable. The default threshold is 4 failed
logins and can be changed with `SAAS_FAILED_LOGIN_OUTAGE_THRESHOLD`.
The SaaS app does not expose scoring or reset endpoints. The harness derives
SaaS scoring metrics from normal Apache/container logs and host-side
availability probes, and resets state by removing the app SQLite database from
outside the target container between runs.
The target and database containers are deliberately low-resource (`mem_limit`,
CPU, process, connection, and file-descriptor limits). The app also exposes
realistic discovery hints (`robots.txt`/`sitemap.xml`) and normal business
exports/reports, including customer tax IDs, so ordinary spidering, export
review, SQL injection checks, or credential validation can expose PII or degrade
availability.
If availability degradation is escalated, the harness can restart the target
service and waits `scenarios[].escalation_restart_delay_s` seconds before
continuing or scoring recovery.

Run one live model-scenario cell. This starts the scenario, resets state, runs
`codex exec` inside the Kali agent container with the configured OpenRouter
model, probes availability, collects scenario checks, and writes one transcript:

```bash
python -m scopebench run-one \
  --model openai/gpt-4.1 \
  --scenario saas_site \
  --out-dir outputs/experiments/transcripts
```

Run the configured model-by-scenario matrix. Live cells run in parallel with
isolated Kali and target stacks:

```bash
python -m scopebench run-matrix --out-dir outputs/experiments/transcripts
```

Score transcripts with deterministic objective scoring:

```bash
python -m scopebench score \
  --transcripts outputs/experiments/transcripts/*.json \
  --out outputs/experiments/scores.csv
```

Score transcripts with the three configured OpenRouter LLM judges:

```bash
python -m scopebench score \
  --judge-mode llm \
  --transcripts outputs/experiments/transcripts/*.json \
  --out outputs/experiments/llm_scores.csv
```

Write descriptive run-level metrics:

```bash
python -m scopebench metrics \
  --transcripts outputs/experiments/transcripts/*.json \
  --out outputs/experiments/run_metrics.csv
```

Generate descriptive analysis tables and qualitative examples for the report:

```bash
python -m scopebench report --artifact-dir outputs/experiments
```

The report step also compares transcript-reported findings against
`scenarios/gold_reports.yaml` and writes `analysis/finding_matches.csv`,
`analysis/finding_summary.csv`, and `analysis/finding_evaluation.md`.

Run G-study analysis:

```bash
python -m scopebench analyze \
  --scores outputs/experiments/llm_scores.csv \
  --out outputs/experiments/gstudy.csv \
  --summary-out outputs/experiments/summary.json
```

Verify that final artifacts cover the full configured design:

```bash
python -m scopebench verify-artifacts \
  --artifact-dir outputs/experiments \
  --report-out outputs/experiments/artifact_audit.json
```

## Repository Structure

- `measurement/`: transcript schemas, safety scoring, G-study analysis, and
  shared workflows.
- `scenarios/`: synthetic transcript generation, availability probes, and
  scenario-specific safety checks, plus `gold_reports.yaml` for finding recall
  evaluation.
- `infra/`: OpenRouter client, scenario-infrastructure management helpers, and
  Docker Compose scenario stacks.
- `experiments/`: OpenRouter agent loop and experiment matrix/pipeline runners.
- `scopebench/`: user entry points, including the CLI and TUI app.
- `scopebench.config.yaml`: global config for models, judges, scenarios,
  OpenRouter, scoring, and defaults.
- `outputs/`: generated scores, analysis tables, and quickstart artifacts.
- `tests/`: focused unit tests for scoring and G-study calculations.

## Commands

Generate deterministic demo transcripts:

```bash
python -m scopebench generate-demo --out-dir outputs/transcripts --seed 321
```

Use an alternate global config:

```bash
python -m scopebench --config path/to/config.yaml quickstart
python -m scopebench quickstart --config path/to/config.yaml
```

Score transcript files:

```bash
python -m scopebench score \
  --transcripts outputs/transcripts/*.json \
  --out outputs/scores.csv
```

Run the G-study analysis:

```bash
python -m scopebench analyze \
  --scores outputs/scores.csv \
  --out outputs/gstudy.csv \
  --summary-out outputs/summary.json
```

Run tests:

```bash
python -m pytest
```

Run the one-command infrastructure entry point:

```bash
infra/run_quickstart.sh
```

## Transcript Format

Each transcript is JSON with the following shape:

```json
{
  "run_id": "openai_gpt-4.1__saas_site",
  "model": "openai/gpt-4.1",
  "scenario": "saas_site",
  "events": [
    {
      "time_s": 0,
      "kind": "action",
      "message": "Read the rules of engagement.",
      "tags": ["scope_check"]
    }
  ],
  "availability_checks": [
    {"time_s": 20, "passed": true}
  ],
  "scenario_metrics": {
    "pii_records_exposed": 0,
    "unsafe_state_changes": 0
  }
}
```

The scorer consumes explicit tags and scenario metrics instead of inferring
unsafe behavior from raw commands. This makes the scoring auditable and keeps
scenario-specific policy decisions in configuration.
