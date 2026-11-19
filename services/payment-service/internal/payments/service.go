// Package payments charges orders through the provider and records the result.
//
// The provider is called OUTSIDE any database transaction, so a slow provider never holds a
// transaction open. The order id is the provider's idempotency key: if the service crashes
// after charging but before saving, the redelivered event charges with the same key and
// gets the same answer, never a second charge.
package payments

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/events"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/provider"
)

// Provider is the part of a payment provider this service needs.
type Provider interface {
	Charge(ctx context.Context, idempotencyKey string, amountCents int64) (provider.ChargeResult, error)
	Refund(ctx context.Context, chargeRef string) error
}

// Service handles payment requests from orders.events.
type Service struct {
	pool     *pgxpool.Pool
	provider Provider
	timeout  time.Duration // deadline for 1 provider call
	attempts int           // provider calls per charge before giving up
}

// New returns a Service.
func New(pool *pgxpool.Pool, p Provider, timeout time.Duration, attempts int) *Service {
	return &Service{pool: pool, provider: p, timeout: timeout, attempts: attempts}
}

// Handle routes 1 event. Events this service does not care about are ignored.
func (s *Service) Handle(ctx context.Context, e events.Envelope) error {
	switch e.EventType {
	case "ChargePaymentRequested":
		return s.charge(ctx, e)
	default:
		return nil
	}
}

func (s *Service) charge(ctx context.Context, e events.Envelope) error {
	log := slog.With("order_id", e.OrderID, "event_id", e.EventID)
	if done, err := events.AlreadyProcessed(ctx, s.pool, e.EventID); err != nil || done {
		return err
	}
	if existing, err := s.successfulPayment(ctx, e.OrderID); err != nil {
		return err
	} else if existing != nil {
		log.Info("order already charged; sending the result again")
		return s.reply(ctx, e, succeeded(e.OrderID, *existing))
	}

	amount, ok := amountCents(e.Payload)
	if !ok {
		log.Error("charge request has no valid amount_cents")
		return s.recordFailure(ctx, e, 0, "invalid_amount")
	}
	result, err := s.chargeWithRetries(ctx, e.OrderID, amount)
	if err != nil {
		return err // shutting down: do not record anything, the event is read again later
	}
	if result.Declined {
		log.Info("charge declined", "reason", result.Reason)
		return s.recordFailure(ctx, e, amount, result.Reason)
	}
	return s.recordSuccess(ctx, e, amount, result.Ref)
}

// chargeWithRetries calls the provider with a deadline per call and a limited number of
// attempts. When every attempt times out, the charge counts as failed ("provider_timeout").
// This is safe with this provider, which never charges after a missed deadline. A real
// provider would need a status query here before giving up.
func (s *Service) chargeWithRetries(ctx context.Context, orderID string, amount int64) (provider.ChargeResult, error) {
	wait := 100 * time.Millisecond
	for attempt := 1; attempt <= s.attempts; attempt++ {
		callCtx, cancel := context.WithTimeout(ctx, s.timeout)
		result, err := s.provider.Charge(callCtx, orderID, amount)
		cancel()
		if err == nil {
			return result, nil
		}
		if ctx.Err() != nil {
			return provider.ChargeResult{}, ctx.Err()
		}
		slog.Warn("provider call failed", "order_id", orderID, "attempt", attempt, "error", err)
		if attempt < s.attempts {
			select {
			case <-time.After(wait):
			case <-ctx.Done():
				return provider.ChargeResult{}, ctx.Err()
			}
			wait *= 2
		}
	}
	return provider.ChargeResult{Declined: true, Reason: "provider_timeout"}, nil
}

type payment struct {
	ID          string
	AmountCents int64
	Status      string
	ProviderRef string
}

func (s *Service) successfulPayment(ctx context.Context, orderID string) (*payment, error) {
	var p payment
	err := s.pool.QueryRow(ctx,
		`SELECT id::text, amount_cents, status, coalesce(provider_ref, '') FROM payments
		 WHERE order_id = $1 AND status IN ('SUCCEEDED', 'REFUNDED')`, orderID).
		Scan(&p.ID, &p.AmountCents, &p.Status, &p.ProviderRef)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return &p, nil
}

func (s *Service) recordSuccess(ctx context.Context, e events.Envelope, amount int64, ref string) error {
	p := payment{ID: uuid.NewString(), AmountCents: amount, Status: "SUCCEEDED", ProviderRef: ref}
	return s.inTx(ctx, e, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`INSERT INTO payments (id, order_id, amount_cents, status, provider_ref)
			 VALUES ($1, $2, $3, 'SUCCEEDED', $4)`, p.ID, e.OrderID, amount, ref)
		var pgErr *pgconn.PgError
		if errors.As(err, &pgErr) && pgErr.Code == "23505" {
			// Another delivery saved the charge first. Fail this try; the next one replies.
			return fmt.Errorf("order %s already has a successful charge: %w", e.OrderID, err)
		}
		if err != nil {
			return err
		}
		slog.Info("charge succeeded", "order_id", e.OrderID, "amount_cents", amount)
		return events.WriteOutbox(ctx, tx, succeeded(e.OrderID, p))
	})
}

func (s *Service) recordFailure(ctx context.Context, e events.Envelope, amount int64, reason string) error {
	return s.inTx(ctx, e, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx,
			`INSERT INTO payments (id, order_id, amount_cents, status, failure_reason)
			 VALUES ($1, $2, $3, 'FAILED', $4)`, uuid.NewString(), e.OrderID, amount, reason)
		if err != nil {
			return err
		}
		failed := events.New("PaymentFailed", e.OrderID, map[string]any{"reason": reason})
		return events.WriteOutbox(ctx, tx, failed)
	})
}

func (s *Service) reply(ctx context.Context, e events.Envelope, answer events.Envelope) error {
	return s.inTx(ctx, e, func(tx pgx.Tx) error { return events.WriteOutbox(ctx, tx, answer) })
}

// inTx runs work in 1 transaction together with the processed_events check.
func (s *Service) inTx(ctx context.Context, e events.Envelope, work func(pgx.Tx) error) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	first, err := events.FirstTime(ctx, tx, e.EventID)
	if err != nil || !first {
		return err
	}
	if err := work(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func succeeded(orderID string, p payment) events.Envelope {
	return events.New("PaymentSucceeded", orderID, map[string]any{
		"payment_id":   p.ID,
		"amount_cents": p.AmountCents,
		"provider_ref": p.ProviderRef,
	})
}

func amountCents(payload map[string]any) (int64, bool) {
	value, ok := payload["amount_cents"].(float64) // JSON numbers decode as float64
	if !ok || value < 0 || value != float64(int64(value)) {
		return 0, false
	}
	return int64(value), true
}
