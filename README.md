# DriveNow – Vehicle Management System

Internal service for a car rental company to manage a fleet of vehicles and their
rentals. Built as a clean, layered foundation for future expansion.

> **Status:** skeleton (steps 0–1 of 13). Architecture is designed and the project
> boots; business logic, endpoints, tests, metrics and the message queue are added
> in later steps. See [docs/architecture.md](docs/architecture.md).

## Tech stack

| Concern | Choice |
|---|---|
| API | FastAPI + Uvicorn |
| Database | PostgreSQL via SQLAlchemy 2.0 + Alembic |
| Metrics | prometheus-client (`/metrics`) |
| Message queue | RabbitMQ (pika) |
| Dependency management | Poetry |
| Tests | pytest |
| Packaging | Docker + docker-compose |

Why PostgreSQL: the data is relational (`rentals.car_id` → `cars`), rental
registration needs an atomic "create rental + flip car status" transaction, and
DB constraints keep invalid data out. Full rationale in
[docs/architecture.md](docs/architecture.md#5-why-postgresql).

## Architecture at a glance

```
HTTP  ─►  API layer      (app/api)          routers, HTTP <-> DTO only
          Service layer  (app/services)     business rules, transactions, events
          Repository     (app/repositories) all DB queries
          ORM models     (app/models)       SQLAlchemy models + CarStatus
          PostgreSQL

Cross-cutting (app/core): config · logging · metrics · db session · DI
Side channel  (app/messaging): EventPublisher ─► RabbitMQ
```

Dependencies point one way only (API → Service → Repository → Models). Diagrams
and the SOLID mapping are in [docs/architecture.md](docs/architecture.md).

## Project layout

```
app/
  api/          FastAPI routers, DI providers, HTTP error mapping
  services/     business logic + domain exceptions
  repositories/ data access layer
  models/       SQLAlchemy models, CarStatus enum
  schemas/      Pydantic request/response DTOs
  messaging/    EventPublisher (Protocol), NullPublisher, consumer worker
  core/         config, logging, metrics
  main.py       application factory
tests/          pytest suite
docs/           architecture.md
```

## Run it

### Local (Poetry)

```bash
poetry install
cp .env.example .env
poetry run uvicorn app.main:app --reload --port 8000
```

- API docs (Swagger): http://localhost:8000/docs
- Health: http://localhost:8000/health
- Metrics: http://localhost:8000/metrics

> Local runs need a reachable PostgreSQL (see `DATABASE_URL`). Easiest is
> `docker compose up -d db`. In the skeleton no code touches the DB yet, so the
> app also boots without one.

### Docker

```bash
docker compose up --build
```

Starts `db` (PostgreSQL), `rabbitmq` (with management UI on :15672), `api` on
:8000, and the `consumer` worker.

## Tests

```bash
poetry run pytest
```

## Lint / type-check

```bash
poetry run ruff check .
poetry run mypy app
```

## Roadmap

| # | Step |
|---|---|
| 0–1 | Architecture + project skeleton *(done)* |
| 2 | DB models, session, Alembic migration |
| 3 | Repository layer |
| 4 | Pydantic DTOs |
| 5 | Service layer (car + rental lifecycle) |
| 6 | REST endpoints |
| 7 | Logging of critical actions |
| 8 | Prometheus metrics |
| 9 | RabbitMQ publisher + consumer |
| 10 | Unit tests (≥ 4) |
| 11 | Docker polish |
| 12 | README: diagrams, examples, screenshots |
| 13 | Git: feature branch, PR |
