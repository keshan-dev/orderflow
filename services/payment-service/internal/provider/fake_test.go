package provider

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestChargeIsIdempotentPerKey(t *testing.T) {
	fake := NewFake(0, 0)
	first, err := fake.Charge(context.Background(), "order-1", 500)
	if err != nil || first.Declined || first.Ref == "" {
		t.Fatalf("unexpected first charge: %+v %v", first, err)
	}
	again, _ := fake.Charge(context.Background(), "order-1", 500)
	if again != first {
		t.Fatalf("same key must return the same answer: %+v vs %+v", again, first)
	}
	other, _ := fake.Charge(context.Background(), "order-2", 500)
	if other.Ref == first.Ref {
		t.Fatal("different keys must be different charges")
	}
}

func TestFailureRateDeclines(t *testing.T) {
	always := NewFake(1, 0)
	result, _ := always.Charge(context.Background(), "k", 1)
	if !result.Declined || result.Reason != "card_declined" {
		t.Fatalf("rate 1 must always decline: %+v", result)
	}
	never := NewFake(0, 0)
	if result, _ := never.Charge(context.Background(), "k", 1); result.Declined {
		t.Fatal("rate 0 must never decline")
	}
}

func TestDeclineIsAlsoRemembered(t *testing.T) {
	fake := NewFake(0.5, 0)
	calls := 0
	fake.chance = func() float64 { calls++; return 0.1 } // below the rate: decline
	first, _ := fake.Charge(context.Background(), "k", 1)
	second, _ := fake.Charge(context.Background(), "k", 1)
	if !first.Declined || second != first || calls != 1 {
		t.Fatalf("a decline must be remembered too: %+v %+v calls=%d", first, second, calls)
	}
}

func TestSlowProviderRespectsTheDeadlineAndChargesNothing(t *testing.T) {
	fake := NewFake(0, time.Second)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	if _, err := fake.Charge(ctx, "k", 1); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("want deadline exceeded, got %v", err)
	}
	if len(fake.charges) != 0 {
		t.Fatal("a timed out call must not charge")
	}
}
