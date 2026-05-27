# Experiment Runbook

This directory contains the runnable experiment harness for the plan in
`plan.pdf`.

## Preflight

```bash
python -m scopebench preflight --live-scenarios
```

Set an OpenRouter key for live model and LLM-judge calls:

```bash
export OPENROUTER_API_KEY=...
```

Live preflight builds each scenario stack, validates the configured
OpenRouter model IDs, resets each target, probes availability, confirms the
Kali agent image exposes the configured Codex CLI version, and checks that the
agent container received the OpenRouter API key environment variable.

## Dry Pipeline

Dry mode verifies artifact generation without Docker or API calls:

```bash
python -m scopebench run-pipeline --dry-run --out-dir outputs/dry_pipeline
```

## Live Matrix

Run the two-scenario by four-model matrix and collect transcripts:

```bash
python -m scopebench run-matrix --out-dir outputs/experiments/transcripts
```

Live runs use `experiment.agent_backend: codex_cli` by default. The harness runs
`codex exec` inside the Kali agent container, enables the Codex goal feature,
points Codex at the configured OpenRouter provider, and resumes the same Codex
session until `experiment.time_limit_s` expires (`3600` seconds by default).
`experiment.max_steps: null` is retained for the legacy `openrouter_json`
backend, but the final experiment path is the Codex CLI scaffold. Matrix runs
start every selected model-scenario cell in parallel by default. Each cell uses
a unique Docker Compose project with its own Kali agent, target services,
internal network, and volumes. Set `experiment.parallel_cells` to cap
concurrency when local CPU, memory, or API-rate limits require it.
The configured `models` and `judges` are OpenRouter model IDs directly. Codex
output is streamed during live runs; provider errors matching
`experiment.provider_error_abort_patterns` are logged immediately and, by
default, abort the affected cell instead of waiting for the full time limit.

Score with the three configured LLM judges:

```bash
python -m scopebench score \
  --judge-mode llm \
  --transcripts outputs/experiments/transcripts/*.json \
  --out outputs/experiments/llm_scores.csv
```

Generate descriptive metrics and G-study outputs:

```bash
python -m scopebench metrics \
  --transcripts outputs/experiments/transcripts/*.json \
  --out outputs/experiments/run_metrics.csv

python -m scopebench analyze \
  --scores outputs/experiments/llm_scores.csv \
  --out outputs/experiments/gstudy.csv \
  --summary-out outputs/experiments/summary.json

python -m scopebench report --artifact-dir outputs/experiments
```

The report command includes a finding evaluation pass. It compares each
transcript against the scenario gold reports in `scenarios/gold_reports.yaml`
and writes `analysis/finding_matches.csv`, `analysis/finding_summary.csv`, and
`analysis/finding_evaluation.md`.

Verify artifact coverage before using the outputs in the manuscript:

```bash
python -m scopebench verify-artifacts \
  --artifact-dir outputs/experiments \
  --report-out outputs/experiments/artifact_audit.json
```

The verifier checks that:

- every configured model-scenario cell has exactly one transcript
- transcripts include model messages, observations, rules of engagement,
  availability checks, and scenario-specific objective metrics
- run metrics and score rows cover the configured design
- score rows form the full model-scenario-judge-dimension matrix
- G-study components and summary counts match the configured facets
- descriptive analysis tables and qualitative examples exist for the manuscript

`run-pipeline` combines these steps. Use deterministic scoring for local
smoke-tests and LLM judge scoring for the final measurement run:

```bash
python -m scopebench run-pipeline \
  --judge-mode llm \
  --out-dir outputs/experiments
```
