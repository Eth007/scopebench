# scopebench

scopebench is a measurement framework for evaluating safe cybersecurity
capability in autonomous penetration-testing agents. It runs models against
sandboxed Docker scenarios, records transcripts, scores operational safety,
matches reported findings against gold reports, and estimates reliability with
Generalizability Theory.

The intended way to use the framework is the terminal UI:

```bash
python -m scopebench tui
```

## Setup

Requirements:

- Python 3.11 or newer
- Docker with the Compose plugin
- Network access to OpenRouter for live model runs and LLM finding matching
- Enough OpenRouter credits for the configured models
- No GPU is required

Install Python dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure the OpenRouter key either as an environment variable:

```bash
export OPENROUTER_API_KEY=...
```

or by replacing the placeholder in [scopebench.config.yaml](scopebench.config.yaml).
The config file also controls model IDs, judge model IDs, scenarios, time
limits, scoring weights, output paths, and concurrency.

Before a live run, check the environment:

```bash
python -m scopebench preflight --live-scenarios
```

This verifies Docker, scenario health, configured OpenRouter model IDs, and the
Codex CLI installed in the Kali agent image.

## Main TUI Workflow

Start the TUI:

```bash
python -m scopebench tui
```

Use these menus:

1. `Run batch`
   Choose the experiment to run. For the paper result, use the full configured
   model-by-scenario matrix. The same menu also supports a single model/scenario
   cell or a selected subset.

2. `Testing and utilities`
   Run quickstart, dry pipeline checks, live smoke tests, and artifact
   verification before spending API credits on the full batch.

3. `Inspect`
   View config, scenario catalog, infrastructure status, recent run logs, summary
   tables, charts, and previous run artifacts.

During a live run, the TUI streams progress, Codex output, Docker lifecycle
events, availability probes, scoring steps, and failures. Use `PageUp` and
`PageDown` to scroll logs, `Home` to jump to the top, and `End` to return to
tail-follow mode. Each TUI run is written to a timestamped directory under
`outputs/tui/runs/`.

## Reproducing the Included Results

The committed result artifacts used by the paper are in [results/](results/).
The primary final run is stored at the root of that directory:

- [results/transcripts/](results/transcripts/): 8 model-scenario transcripts
- [results/run_metrics.csv](results/run_metrics.csv): availability and scenario
  metrics
- [results/scores.csv](results/scores.csv): deterministic safety scores
- [results/analysis/finding_summary.csv](results/analysis/finding_summary.csv):
  finding recall against gold reports
- [results/gstudy.csv](results/gstudy.csv): G-study variance components
- [results/summary.json](results/summary.json): aggregate reliability summary

To reproduce the full workflow from scratch through the TUI:

1. Set `OPENROUTER_API_KEY`.
2. Run `python -m scopebench tui`.
3. Open `Testing and utilities` and run the live preflight.
4. Open `Run batch`.
5. Choose `Run full batch`.
6. After completion, open `Inspect` to view the run summary and logs.
7. Use `Verify full batch artifacts` or run the verification command below.

Equivalent CLI command for a full run:

```bash
python -m scopebench run-pipeline --out-dir outputs/reproduction/full_batch
```

Verify a completed artifact directory:

```bash
python -m scopebench verify-artifacts \
  --artifact-dir outputs/reproduction/full_batch \
  --report-out outputs/reproduction/full_batch/artifact_audit.json
```

Run a no-cost offline smoke test:

```bash
python -m scopebench quickstart
```

The quickstart uses deterministic synthetic transcripts and writes to
`outputs/quickstart/`.

Artifact map for the paper:

- `Run full batch` in the TUI, or `python -m scopebench run-pipeline`, produces
  transcripts, `run_metrics.csv`, `scores.csv`, `gstudy.csv`, `summary.json`,
  `artifact_audit.json`, and the `analysis/` report files.
- `Generate full batch report` in the TUI, or `python -m scopebench report`,
  regenerates `analysis/finding_summary.csv`,
  `analysis/finding_evaluation.md`, model/scenario summaries, and qualitative
  examples from an existing artifact directory.
- `Verify full batch artifacts` in the TUI, or
  `python -m scopebench verify-artifacts`, produces `artifact_audit.json`.
- The paper tables are read from the committed `results/` files:
  finding recall from `results/analysis/finding_summary.csv`, safety metrics
  from `results/run_metrics.csv`, safety scores from `results/scores.csv`, and
  G-study results from `results/gstudy.csv` and `results/summary.json`.

## Runtime and Compute

The default live experiment time limit is configured in
[scopebench.config.yaml](scopebench.config.yaml). In the current config it is
`1800` seconds per model-scenario cell, with availability checks every 20
seconds and a final-report grace period before shutdown.

Expected runtime:

- Quickstart: under 5 seconds, no Docker or API key required
- Live preflight: a few minutes, depending on Docker image builds
- Full live batch: about one cell time limit plus Docker/scoring overhead when
  all cells run in parallel; longer if `experiment.parallel_cells` caps
  concurrency

Computational requirements are modest: CPU-only Docker containers, local disk
for transcripts/logs, and OpenRouter API credits. The Kali agent image installs
Codex CLI, nmap, sqlmap, curl, jq, Python, and related tools.

Reproducibility notes:

- Python dependencies are pinned in [requirements.txt](requirements.txt).
- The default synthetic-data seed is `defaults.random_seed: 321` in
  [scopebench.config.yaml](scopebench.config.yaml), and demo commands accept
  `--seed`.
- Live model behavior can vary because OpenRouter model backends are external
  services; the framework preserves exact transcripts and run manifests so each
  completed run can be audited afterward.
- The TUI and CLI workflows run end-to-end without code edits once Docker and
  `OPENROUTER_API_KEY` are available.

## Data and Scenario Generation

No external datasets are required. All targets and records are generated inside
local sandbox scenarios:

- `saas_site`: a PHP business web application with seeded fictitious customer
  records, reports, diagnostics, and realistic web vulnerabilities
- `water_ics`: a simulated water-treatment SCADA/Modbus environment with
  process variables and safety-relevant controls

Gold findings are stored in [scenarios/gold_reports.yaml](scenarios/gold_reports.yaml).
The framework compares agent reports to those gold findings and applies severity
weights from [scopebench.config.yaml](scopebench.config.yaml). Generated
transcripts and scoring outputs are written under `outputs/` for new runs, while
the paper's committed artifacts are under `results/`.

## Repository Structure

- `scopebench/`: CLI and TUI entry points
- `experiments/`: Codex/OpenRouter agent loop and batch pipeline
- `infra/`: Docker lifecycle helpers, OpenRouter client, and scenario stacks
- `infra/saas_site/`: SaaS target Docker environment
- `infra/water_ics/`: water-treatment ICS target Docker environment
- `measurement/`: transcript schemas, metrics, safety scoring, finding matching,
  reports, artifact audits, and G-study analysis
- `scenarios/`: scenario probes, checks, demo transcript generation, and gold
  reports
- `tests/`: unit tests for config, scoring, findings, scenarios, TUI, and
  pipeline behavior
- `paper/`: paper source
- `results/`: committed result artifacts used by the paper
- `outputs/`: default location for newly generated local runs

## Useful Commands

Run tests:

```bash
python -m pytest
```

Validate configured OpenRouter model IDs:

```bash
python -m scopebench validate-models
```

Generate a report for an artifact directory:

```bash
python -m scopebench report --artifact-dir outputs/reproduction/full_batch
```

Use a different config file:

```bash
python -m scopebench --config path/to/config.yaml tui
```
