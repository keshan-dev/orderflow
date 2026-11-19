-- +goose Up
CREATE TABLE payments (
    id             uuid PRIMARY KEY,
    order_id       uuid NOT NULL,
    amount_cents   integer NOT NULL CHECK (amount_cents >= 0),
    status         text NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED', 'REFUNDED')),
    provider_ref   text,
    failure_reason text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now()
);
-- An order can have many failed attempts but only 1 successful (or later refunded) charge.
CREATE UNIQUE INDEX payments_one_charge_per_order
    ON payments (order_id) WHERE status IN ('SUCCEEDED', 'REFUNDED');

CREATE TABLE outbox (
    id            uuid PRIMARY KEY,
    aggregatetype text NOT NULL,
    aggregateid   text NOT NULL,
    type          text NOT NULL,
    payload       jsonb NOT NULL,
    traceparent   text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE processed_events (
    event_id     uuid PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);

CREATE PUBLICATION dbz_outbox FOR TABLE outbox;

-- +goose Down
DROP PUBLICATION IF EXISTS dbz_outbox;
DROP TABLE processed_events;
DROP TABLE outbox;
DROP TABLE payments;
