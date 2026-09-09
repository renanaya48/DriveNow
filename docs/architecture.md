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
  CHECK end_date >= start_date                              (ck_rentals_end_after_start)
  CHECK returned_date IS NULL OR returned_date >= start_date (ck_rentals_returned_after_start)
  UNIQUE (car_id) WHERE returned_date IS NULL               (uq_rentals_one_active_per_car)
```

**Active rental** = row with `returned_date IS NULL`. Keeping `returned_date`
separate from the agreed `end_date` lets us later detect late returns
(`returned_date > end_date`). The partial unique index enforces **at most one
open rental per car** at the DB level.

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

### 2.4 Service layer

`app/services/` — `CarService` (`add_car`, `update_car`, `list_cars`,
`delete_car`) and `RentalService` (`register_rental`, `end_rental`). Plain Python,
no FastAPI. Each service holds a `UnitOfWork` + the repositories + an
`EventPublisher`, all sharing one DB session.

**Transaction ownership.** Repositories `flush` but never commit. Each service
method runs its repository calls inside `_transaction()`: commit on a clean exit,
`rollback()` + re-raise on any exception. Events are published **after** commit
and are **best-effort** — a publish failure is logged, never rolls anything back.
*Event publication is deliberately best-effort for this assignment; a production
system needing guaranteed delivery would use the transactional outbox pattern.*

**Concurrency — global lock order: CAR → RENTAL.** Every lifecycle operation
takes the car row lock (`get_by_id_for_update`, `SELECT … FOR UPDATE` on
PostgreSQL, no-op on SQLite) so they serialise:

| Operation | Locks (in order) |
|---|---|
| `update_car` / `delete_car` / `register_rental` | car |
| `end_rental` | unlocked read of the rental for its `car_id` → **car** → re-read rental **for update** (`populate_existing`) → validate the locked rental |

Every operation needing both locks acquires them in the **same** order
(CAR → RENTAL); no operation acquires them in the opposite order, so there is no
lock-order cycle.

**One open rental per car** is guarded in three layers:

1. `car.status == AVAILABLE` check;
2. explicit `rentals.get_active_by_car` after the lock — this is what converts an
   inconsistent row (`AVAILABLE` yet an open rental exists) into a domain-level
   `CarNotAvailableError`;
3. the partial unique index `uq_rentals_one_active_per_car` — the final database
   integrity backstop (it raises `IntegrityError` if the code path ever reaches it).

**Status transitions** (enforced by `update_car`): `AVAILABLE ↔ UNDER_MAINTENANCE`
only; `IN_USE` is entered by `register_rental` and left by `end_rental`. A
same-value or empty update is a no-op — no write, no event.

**`register_rental` starts a rental today** — not a reservation system, not
historical import: `dto.start_date` must equal today.

**Domain events** (minimal payloads; the publisher adds id/timestamp envelope
metadata in step 9):

| Event | Payload |
|---|---|
| `car.added` / `car.deleted` | `{"car_id": int}` |
| `car.updated` | `{"car_id": int, "changed": [field, …]}` |
| `rental.started` / `rental.ended` | `{"rental_id": int, "car_id": int}` |

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
    Note over S: reject unless start_date == today (RentalDateError)
    S->>CR: get_by_id_for_update(car_id)  %% SELECT ... FOR UPDATE
    CR->>DB: SELECT car FOR UPDATE
    alt car missing / soft-deleted
        S-->>API: CarNotFoundError
        API-->>C: 404
    else car.status != available OR open rental exists
        S-->>API: CarNotAvailableError
        API-->>C: 409
    else ok
        S->>RR: add(rental)  %% returned_date = NULL
        S->>CR: car.status = in_use ; update(car)
        S->>DB: uow.commit()  %% one atomic transaction
        S->>P: publish("rental.started", {...})  %% best-effort, after commit
        S-->>API: Rental
        API-->>C: 201 RentalRead
    end
```

### 3.2 End a rental — `POST /rentals/{id}/end`

```mermaid
sequenceDiagram
    participant C as Client
    participant API as API (rentals router)
    participant S as RentalService
    participant CR as CarRepository
    participant RR as RentalRepository
    participant DB as PostgreSQL
    participant P as EventPublisher

    C->>API: POST /rentals/{id}/end
    API->>S: end_rental(id)
    S->>RR: get_by_id(id)  %% unlocked, to discover car_id
    alt rental missing
        S-->>API: RentalNotFoundError
        API-->>C: 404
    else ok
        S->>CR: get_by_id_for_update(car_id)   %% lock CAR first
        S->>RR: get_by_id_for_update(id)       %% then lock + re-read RENTAL
        alt rental.returned_date is not null
            S-->>API: RentalAlreadyEndedError
            API-->>C: 409
        else ok
            S->>RR: rental.returned_date = today() ; update(rental)
            S->>CR: car.status = available ; update(car)
            S->>DB: uow.commit()
            S->>P: publish("rental.ended", {...})
            S-->>API: Rental
            API-->>C: 200 RentalRead
        end
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
