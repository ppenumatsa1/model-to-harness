# Project structure

`docs/` contains the checkout domain contract. Each implementation below it
owns its own API, harness integration, database adapter, UI, telemetry,
infrastructure, tests, and deployment evidence.

```text
checkout-recovery/
  docs/                  framework-neutral checkout contract
  maf/                   first independent implementation
  <future-harness>/      future independent implementation
```

Framework-neutral checkout records, deterministic simulators, fixtures, and
evaluation contracts belong in the repository root `shared/` package. No
application API, persistence adapter, cloud client, telemetry code, UI, or
deployment code belongs there.
