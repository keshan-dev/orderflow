package payments

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/db"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/events"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/provider"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/testdb"
)

func newService(t *testing.T, p Provider, timeout time.Duration) (*Service, *pgxpool.Pool) {
	t.Helper()
	ctx := context.Background()
	url := testdb.New(t)
	if err := db.Migrate(ctx, url); err != nil {
		t.Fatal(err)
	}
	pool, err := db.NewPool(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	return New(pool, p, timeout, 3), pool
}

func chargeRequest(orderID string, amount float64) events.Envelope {
	return events.New("ChargePaymentRequested", orderID, map[string]any{"amount_cents": amount})
}

func outboxTypes(t *testing.T, pool *pgxpool.Pool) []string {
	t.Helper()
	rows, err := pool.Query(context.Background(), `SELECT type FROM outbox ORDER BY created_at`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var types []string
	for rows.Next() {
		var kind string
		_ = rows.Scan(&kind)
		types = append(types, kind)
	}
	return types
}

func countPayments(t *testing.T, pool *pgxpool.Pool, status string) int {
	t.Helper()
	var n int
	_ = pool.QueryRow(context.Background(),
		`SELECT count(*) FROM payments WHERE status = $1`, status).Scan(&n)
	return n
}

func TestSuccessfulChargeIsRecordedWithItsEvent(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	if err := svc.Handle(context.Background(), chargeRequest(uuid.NewString(), 7999)); err != nil {
		t.Fatal(err)
	}
	if got := outboxTypes(t, pool); len(got) != 1 || got[0] != "PaymentSucceeded" {
		t.Fatalf("outbox = %v", got)
	}
	if countPayments(t, pool, "SUCCEEDED") != 1 {
		t.Fatal("want 1 successful payment")
	}
}

func TestSameRequestTwiceChargesOnce(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	request := chargeRequest(uuid.NewString(), 500)
	for range 2 {
		if err := svc.Handle(context.Background(), request); err != nil {
			t.Fatal(err)
		}
	}
	if countPayments(t, pool, "SUCCEEDED") != 1 || len(outboxTypes(t, pool)) != 1 {
		t.Fatal("a redelivered request must not charge or reply twice")
	}
}

func TestNewRequestForAChargedOrderRepliesWithoutCharging(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	orderID := uuid.NewString()
	_ = svc.Handle(context.Background(), chargeRequest(orderID, 500))
	_ = svc.Handle(context.Background(), chargeRequest(orderID, 500)) // different event id
	if countPayments(t, pool, "SUCCEEDED") != 1 {
		t.Fatal("must not charge twice")
	}
	if got := outboxTypes(t, pool); len(got) != 2 || got[1] != "PaymentSucceeded" {
		t.Fatalf("the second request still gets an answer: %v", got)
	}
}

func TestDeclinedChargeIsRecordedAsFailed(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(1, 0), time.Second)
	_ = svc.Handle(context.Background(), chargeRequest(uuid.NewString(), 500))
	if got := outboxTypes(t, pool); len(got) != 1 || got[0] != "PaymentFailed" {
		t.Fatalf("outbox = %v", got)
	}
	if countPayments(t, pool, "FAILED") != 1 {
		t.Fatal("want 1 failed payment")
	}
}

func TestSlowProviderFailsTheChargeAfterLimitedRetries(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, time.Second), 20*time.Millisecond)
	started := time.Now()
	if err := svc.Handle(context.Background(), chargeRequest(uuid.NewString(), 500)); err != nil {
		t.Fatal(err)
	}
	if time.Since(started) > 2*time.Second {
		t.Fatal("retries must be limited")
	}
	var reason string
	_ = pool.QueryRow(context.Background(), `SELECT failure_reason FROM payments`).Scan(&reason)
	if reason != "provider_timeout" || countPayments(t, pool, "SUCCEEDED") != 0 {
		t.Fatalf("want a provider_timeout failure, got %q", reason)
	}
}

func TestMissingAmountFailsThePayment(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	request := events.New("ChargePaymentRequested", uuid.NewString(), map[string]any{})
	_ = svc.Handle(context.Background(), request)
	if got := outboxTypes(t, pool); len(got) != 1 || got[0] != "PaymentFailed" {
		t.Fatalf("outbox = %v", got)
	}
}

func refundRequest(orderID string) events.Envelope {
	return events.New("RefundPaymentRequested", orderID, map[string]any{})
}

func TestRefundMarksThePaymentRefundedOnce(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	orderID := uuid.NewString()
	_ = svc.Handle(context.Background(), chargeRequest(orderID, 500))
	request := refundRequest(orderID)
	for range 2 {
		if err := svc.Handle(context.Background(), request); err != nil {
			t.Fatal(err)
		}
	}
	if countPayments(t, pool, "REFUNDED") != 1 || countPayments(t, pool, "SUCCEEDED") != 0 {
		t.Fatal("want exactly 1 refunded payment")
	}
	if got := outboxTypes(t, pool); len(got) != 2 || got[1] != "PaymentRefunded" {
		t.Fatalf("outbox = %v", got)
	}
}

func TestRefundForAnOrderNeverChargedDoesNothing(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	if err := svc.Handle(context.Background(), refundRequest(uuid.NewString())); err != nil {
		t.Fatal(err)
	}
	if got := outboxTypes(t, pool); len(got) != 0 {
		t.Fatalf("nothing to refund, but outbox = %v", got)
	}
}

func TestChargeAfterRefundDoesNotChargeAgain(t *testing.T) {
	svc, pool := newService(t, provider.NewFake(0, 0), time.Second)
	orderID := uuid.NewString()
	_ = svc.Handle(context.Background(), chargeRequest(orderID, 500))
	_ = svc.Handle(context.Background(), refundRequest(orderID))
	_ = svc.Handle(context.Background(), chargeRequest(orderID, 500))
	if countPayments(t, pool, "SUCCEEDED") != 0 || countPayments(t, pool, "REFUNDED") != 1 {
		t.Fatal("a refunded order must never be charged again")
	}
}
