// Package events holds the shared event envelope and the transactional outbox helpers.
//
// Every event has the same envelope: event_id, event_type, order_id, occurred_at, version,
// payload. Events are never sent to Kafka directly: they are written to the outbox table in
// the same transaction as the data change, and Debezium publishes them.
package events

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Aggregate picks the Kafka topic: "payments" goes to payments.events.
const Aggregate = "payments"

// ErrMalformed means a message is not a valid envelope and can never be processed.
var ErrMalformed = errors.New("malformed event envelope")

// Envelope is the shared shape of every OrderFlow event.
type Envelope struct {
	EventID    string         `json:"event_id"`
	EventType  string         `json:"event_type"`
	OrderID    string         `json:"order_id"`
	OccurredAt time.Time      `json:"occurred_at"`
	Version    int            `json:"version"`
	Payload    map[string]any `json:"payload"`
}

// New builds an envelope with a fresh event id.
func New(eventType, orderID string, payload map[string]any) Envelope {
	return Envelope{
		EventID:    uuid.NewString(),
		EventType:  eventType,
		OrderID:    orderID,
		OccurredAt: time.Now().UTC(),
		Version:    1,
		Payload:    payload,
	}
}

// Parse reads an envelope and checks its ids. Errors wrap ErrMalformed.
func Parse(data []byte) (Envelope, error) {
	var e Envelope
	if err := json.Unmarshal(data, &e); err != nil {
		return Envelope{}, fmt.Errorf("%w: %v", ErrMalformed, err)
	}
	if _, err := uuid.Parse(e.EventID); err != nil {
		return Envelope{}, fmt.Errorf("%w: bad event_id", ErrMalformed)
	}
	if _, err := uuid.Parse(e.OrderID); err != nil {
		return Envelope{}, fmt.Errorf("%w: bad order_id", ErrMalformed)
	}
	if e.EventType == "" {
		return Envelope{}, fmt.Errorf("%w: missing event_type", ErrMalformed)
	}
	return e, nil
}

// WriteOutbox adds the event to the outbox inside the caller's transaction.
func WriteOutbox(ctx context.Context, tx pgx.Tx, e Envelope) error {
	body, err := json.Marshal(e)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx,
		`INSERT INTO outbox (id, aggregatetype, aggregateid, type, payload)
		 VALUES ($1, $2, $3, $4, $5::jsonb)`,
		e.EventID, Aggregate, e.OrderID, e.EventType, string(body))
	return err
}

// FirstTime records the event id inside the caller's transaction. False means the event
// was handled before and must be skipped.
func FirstTime(ctx context.Context, tx pgx.Tx, eventID string) (bool, error) {
	var stored string
	err := tx.QueryRow(ctx,
		`INSERT INTO processed_events (event_id) VALUES ($1)
		 ON CONFLICT DO NOTHING RETURNING event_id`, eventID).Scan(&stored)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// AlreadyProcessed is a quick read-only check before doing slow work for an event.
func AlreadyProcessed(ctx context.Context, pool *pgxpool.Pool, eventID string) (bool, error) {
	var exists bool
	err := pool.QueryRow(ctx,
		`SELECT EXISTS (SELECT 1 FROM processed_events WHERE event_id = $1)`, eventID).Scan(&exists)
	return exists, err
}
