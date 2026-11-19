// Package provider is a fake payment provider. It never moves real money.
//
// It behaves like a real provider in the ways that matter for the saga: it can be slow, it
// can decline, and it is idempotent: charging again with the same key returns the first
// answer instead of charging twice.
package provider

import (
	"context"
	crand "crypto/rand"
	"encoding/hex"
	"math/rand/v2"
	"sync"
	"time"
)

// ChargeResult is the provider's answer to 1 charge.
type ChargeResult struct {
	Ref      string // provider's id for the charge
	Declined bool
	Reason   string
}

// Fake is safe for concurrent use.
type Fake struct {
	failureRate float64
	delay       time.Duration
	chance      func() float64

	mu      sync.Mutex
	charges map[string]ChargeResult
}

// NewFake returns a provider that declines failureRate of charges and takes delay per call.
func NewFake(failureRate float64, delay time.Duration) *Fake {
	return &Fake{
		failureRate: failureRate,
		delay:       delay,
		chance:      rand.Float64,
		charges:     make(map[string]ChargeResult),
	}
}

// Charge takes amountCents once per idempotency key. If ctx ends during the delay, nothing
// is charged and ctx.Err() is returned, so a timeout is always safe to retry.
func (f *Fake) Charge(ctx context.Context, idempotencyKey string, amountCents int64) (ChargeResult, error) {
	if err := f.wait(ctx); err != nil {
		return ChargeResult{}, err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if previous, ok := f.charges[idempotencyKey]; ok {
		return previous, nil
	}
	result := ChargeResult{Ref: "ch_" + randomID()}
	if f.chance() < f.failureRate {
		result = ChargeResult{Declined: true, Reason: "card_declined"}
	}
	f.charges[idempotencyKey] = result
	return result, nil
}

// Refund gives a charge back. It is safe to call more than once.
func (f *Fake) Refund(ctx context.Context, chargeRef string) error {
	return f.wait(ctx)
}

func (f *Fake) wait(ctx context.Context) error {
	if f.delay <= 0 {
		return ctx.Err()
	}
	timer := time.NewTimer(f.delay)
	defer timer.Stop()
	select {
	case <-timer.C:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	}
}

func randomID() string {
	b := make([]byte, 8)
	_, _ = crand.Read(b)
	return hex.EncodeToString(b)
}
