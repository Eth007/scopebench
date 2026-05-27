# Scenario Infrastructure

This folder is the operational home for scenario environments and run controls.

Current components:

- `run_quickstart.sh` runs the synthetic end-to-end measurement workflow.
- `manager.py` validates `scopebench.config.yaml`, reports OpenRouter API key
  status, and reports whether live target infrastructure has been configured.
- Models, judges, scenarios, OpenRouter settings, and measurement constants are
  configured in the root `scopebench.config.yaml`.
- `agent/` builds the isolated Kali-based command-execution container.
- `saas_site/` contains the PHP/SQLite SaaS target.
- `water_ics/` contains the water-treatment SCADA/Modbus simulator.

Live scenario layout:

```text
infra/
  agent/
    Dockerfile
  saas_site/
    docker-compose.yml
    app/
  water_ics/
    docker-compose.yml
    app/
```

The matrix runner starts each live cell with a unique Compose project name, so
parallel cells get separate Kali agents, target containers, networks, and
volumes. Each cell uses one isolated Compose bridge network to avoid exhausting
Docker's default address pools during full parallel batches. Target services
publish dynamic loopback-only host ports; the harness discovers the assigned
port with `docker compose port` and uses it only for availability probes and
scenario-specific checks.
