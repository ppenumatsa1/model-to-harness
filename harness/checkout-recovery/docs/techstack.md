# Technology stack

The domain contract requires typed checkout records, deterministic simulators,
fixture/evaluation expectations and PostgreSQL business authority. Neutral
Python models and simulation behavior belong in the root `shared/` package.

Framework SDKs, web frameworks, database drivers, model clients, UI libraries,
telemetry exporters and deployment tooling are implementation choices owned by
each lane. Sharing the domain contract does not require sharing those adapters.

The first implementation's Python/MAF, FastAPI, Psycopg, React and Foundry stack
is documented in the [MAF technology stack](../maf/docs/design/techstack.md),
with its actual manifests and packaging boundaries. Hosted runtime and
investigation framework are separate roles; their concrete products are not
part of a framework-neutral checkout specification.
