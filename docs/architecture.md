# DriveNow – Architecture

## 1. Goal

An internal system for **DriveNow**, a car rental company, to manage a fleet of
vehicles and their rentals. It must be a clean foundation for future expansion,
so the design puts **separation of concerns** and **SOLID** first.

## 2. Layered architecture

Dependencies point in **one direction only** – every layer knows the layer
directly beneath it and never the one above. This lets us swap a layer's
implementation (a different DB, a different message broker) and test each layer
in isolation.

```mermaid
flowchart TD
    client["HTTP client / Swagger UI"]
    subgraph app["Application (app/)"]
        api["API layer — app/api/\nFastAPI routers, HTTP <-> DTO translation only"]
        svc["Service layer — app/services/\nbusiness rules, transactions, emits domain events"]
        repo["Repository layer — app/repositories/\nall DB queries, no business logic"]
        models["ORM models — app/models/\nSQLAlchemy models + CarStatus enum"]
    end
    db[("PostgreSQL")]
    mq{{"RabbitMQ"}}

    core["Cross-cutting — app/core/\nconfig · logging · metrics · db session · DI"]
    pub["app/messaging/\nEventPublisher (Protocol) + NullPublisher / RabbitMQPublisher"]

    client --> api --> svc --> repo --> models --> db
    svc -.->|publish rental.started / rental.ended| pub -.-> mq
    core -.provides.-> api
    core -.provides.-> svc
    core -.provides.-> repo
```

| Layer | Package | Responsibility | Must NOT do |
|---|---|---|---|
| API | `app/api/` | Parse/validate HTTP, call a service, map result/errors to status codes | Business rules, DB access |
| Service | `app/services/` | Enforce business rules, own the DB transaction (Unit of Work), publish events | Know about HTTP, write raw SQL |
| Repository | `app/repositories/` | CRUD + queries against the ORM | Business decisions, commit/rollback policy |
| Models | `app/models/` | Table definitions, column types, `CarStatus` enum | Any logic |
| Cross-cutting | `app/core/` | Settings, logging, metrics, DB session factory, DI providers | Domain rules |
| Messaging | `app/messaging/` | Publish/consume domain events | Be a hard dependency of the request path (best-effort) |

<a id="schema"></a>

### 2.1 Database schema

Managed by Alembic (`alembic/versions/0001_create_cars_and_rentals.py`). Models in
`app/models/`. `CarStatus` maps to `VARCHAR` + a named `CHECK`
(`native_enum=False, create_constraint=True`), storing the enum *values*
(`values_callable`), so the same models run on PostgreSQL and on SQLite (tests).

```
cars
  id           INTEGER  PK
  model        VARCHAR(100)   NOT NULL
  year         INTEGER        NOT NULL
  status       VARCHAR(20)    NOT NULL  DEFAULT 'available'
                 CHECK status IN ('available','in_use','under_maintenance')  (car_status)
  created_at   TIMESTAMPTZ    NOT NULL  DEFAULT now()
  updated_at   TIMESTAMPTZ    NOT NULL  DEFAULT now()
  deleted_at   TIMESTAMPTZ    NULL       -- soft delete: NULL => in fleet
                                         [index ix_cars_deleted_at]

rentals
  id             INTEGER  PK
  car_id         INTEGER        NOT NULL  -> cars(id)        [index ix_rentals_car_id]
  customer_name  VARCHAR(200)   NOT NULL
  start_date     DATE           NOT NULL   -- agreed term, set at registration
  end_date       DATE           NOT NULL   -- agreed term, set at registration
  returned_date  DATE           NULL       -- set when the rental is ended;
                                           -- NULL => still active
                                           [index ix_rentals_returned_date]
  created_at     TIMESTAMPTZ    NOT NULL  DEFAULT now()
  updated_at     TIMESTAMPTZ    NOT NULL  DEFAULT now()
  CHECK end_date >= start_date            (ck_rentals_end_after_start)
```

**Active rental** = row with `returned_date IS NULL`. Keeping `returned_date`
separate from the agreed `end_date` lets us later detect late returns
(`returned_date > end_date`).

**Car removal is a soft delete.** `deleted_at` is stamped instead of deleting the
row, so rental history is never lost and a retired car stays reachable through
`Rental.car`. The `Car.rentals` relationship uses the default cascade only —
removing a car must never touch its rentals.

### 2.2 Repository layer

`app/repositories/` — one narrow interface per aggregate, each backed by a
SQLAlchemy implementation (same shape as `EventPublisher` / `NullPublisher`):

- `CarRepository`: `add`, `get_by_id`, `get_by_id_for_update`, `list(status=None)`, `update`, `soft_delete`
- `RentalRepository`: `add`, `get_by_id`, `get_active_by_car`, `list_active`

Rules:

- Plain Python — **no FastAPI imports**. The session is passed to `__init__`.
- `flush()` to assign PKs / surface constraint errors, but **never `commit` /
  `rollback`** — the transaction (Unit of Work) belongs to the service.
- Return ORM models, never DTOs. "Not found" → return `None`, never raise;
  mapping `None` → `CarNotFoundError` is the service's job.
- `get_by_id_for_update` issues `SELECT … FOR UPDATE` (PostgreSQL row lock;
  no-op on SQLite). Step 5's `register_rental` uses it to serialise concurrent
  bookings of the same car.
- Every `CarRepository` read filters out `deleted_at IS NOT NULL`. `soft_delete`
  stamps `deleted_at`; whether a car *may* be removed (e.g. not while it has an
  active rental) is a business rule enforced by the service in step 5.

### 2.3 API schemas (DTOs)

`app/schemas/` — Pydantic v2 models, one triad per aggregate:

- **`*Create`** — required fields only, no `id` / timestamps. `CarCreate` is
  `model` + `year`; `status` is *not* accepted (a new car is always
  `AVAILABLE` — `IN_USE` only results from registering a rental).
- **`*Update`** — every field optional (PATCH). Empty body `{}` is a valid
  no-op. A field sent explicitly as `null` is rejected (those columns are
  `NOT NULL`); "not sent" ≠ "sent as null".
- **`*Read`** — the shape returned to clients: `id`, timestamps, and computed
  fields (`RentalRead.is_active`, from the ORM property — never stored twice).
  `CarRead` omits `deleted_at` (deleted cars are not returned at all).

Why DTOs are separate from the ORM models: the ORM describes *storage*; the DTO
describes *what a client may send and what we choose to show*. The split gives
over-posting protection, edge validation, and a wire format that stays stable
when the tables change.

Request DTOs subclass `StrictModel` (`extra="forbid"`) — an unknown / over-posted
field is a `422`, not silently dropped. Response DTOs subclass `ORMModel`
(`from_attributes=True`) so they build straight from an ORM instance.

**Three layers of validation:**

| Layer | Question it answers | Examples |
|---|---|---|
| Pydantic (DTO) | Is the request *structurally* valid? | types, `year` in range, non-empty name, `end_date >= start_date`, no unknown fields |
| Service (step 5) | Is the *operation* allowed? | car exists / not soft-deleted / is `AVAILABLE`; rental not already ended; legal status transition |
| Database | Can invalid persisted state still be prevented? | `NOT NULL`, FK, `CHECK` |

The service does not skip validation — it owns the business invariants.

## 3. Key flows

### 3.1 Register a rental — `POST /rentals`

```mermaid
sequenceDiagram
    participant C as Client
    participant API as API (rentals router)
    participant S as RentalService
    participant CR as CarRepository
    participant RR as RentalRepository
    participant DB as PostgreSQL
    participant P as EventPublisher

    C->>API: POST /rentals {car_id, customer_name, start_date, end_date}
    API->>S: register_rental(dto)
    S->>CR: get_by_id(car_id)
    CR->>DB: SELECT car
    alt car missing
        S-->>API: CarNotFoundError
        API-->>C: 404
    else car.status != available
        S-->>API: CarNotAvailableError
        API-->>C: 409
    else ok
        S->>RR: add(rental)  %% start_date, end_date from request; returned_date = NULL
        S->>CR: car.status = in_use
        S->>DB: COMMIT (single transaction)
        S->>P: publish("rental.started", {...})  %% best-effort, after commit
        S-->>API: RentalRead
        API-->>C: 201
    end
```

### 3.2 End a rental — `POST /rentals/{id}/end`

```mermaid
sequenceDiagram
    participant C as Client
    participant API as API (rentals router)
    participant S as RentalService
    participant RR as RentalRepository
    participant DB as PostgreSQL
    participant P as EventPublisher

    C->>API: POST /rentals/{id}/end
    API->>S: end_rental(id)
    S->>RR: get_by_id(id)
    alt rental missing
        S-->>API: RentalNotFoundError
        API-->>C: 404
    else rental.returned_date is not null
        S-->>API: RentalAlreadyEndedError
        API-->>C: 409
    else ok
        S->>RR: rental.returned_date = today()
        S->>RR: rental.car.status = available
        S->>DB: COMMIT
        S->>P: publish("rental.ended", {...})
        S-->>API: RentalRead
        API-->>C: 200
    end
```

## 4. SOLID in this codebase

| Principle | Where |
|---|---|
| **S**ingle Responsibility | `CarService` vs `RentalService`; one router per domain; repositories only query |
| **O**pen/Closed | New event consumers or a new publisher backend added without touching services |
| **L**iskov Substitution | `NullPublisher` and `RabbitMQPublisher` are fully interchangeable behind `EventPublisher` |
| **I**nterface Segregation | Narrow repository interfaces – only the methods a service needs |
| **D**ependency Inversion | Services depend on the `EventPublisher` protocol and repository abstractions rather than concrete implementations. Concrete dependencies are assembled in the API composition root (`app/api/deps.py`) using FastAPI `Depends` |

## 5. Why PostgreSQL

- The data is **inherently relational**: `rentals.car_id` is a foreign key to `cars`,
  and the common query is "active rentals for a car".
- **Transactional integrity matters**: registering a rental must create the rental
  row *and* flip the car's status atomically. A relational DB with ACID
  transactions gives this for free.
- **Constraints as guardrails**: FK constraints, `NOT NULL`, a `CHECK` on
  `status`, and `CHECK (end_date >= start_date)` stop invalid data at the DB level.
- SQLAlchemy 2.0 + Alembic give a clean ORM boundary and versioned migrations,
  so swapping the concrete engine later is a config change, not a rewrite.

A document store (MongoDB) would push join logic and referential integrity into
application code – more work for no benefit at this shape and scale.

## 6. Cross-cutting concerns

- **Logging** (`app/core/logging.py`): stdlib `logging`, `dictConfig`, console +
  `RotatingFileHandler` to `logs/app.log`. Services log add/update/rental
  lifecycle/errors.
- **Metrics** (`app/core/metrics.py`): `prometheus_client` exposed at `/metrics` –
  available cars (gauge), ongoing rentals (gauge), request/operation latency
  (histogram), operation counters.
- **Messaging** (`app/messaging/`): domain events published best-effort after a
  successful commit; a failure to publish is logged, never fatal to the request.
