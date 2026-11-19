package events

import (
	"encoding/json"
	"errors"
	"testing"
)

func TestNewAndParseRoundTrip(t *testing.T) {
	e := New("PaymentSucceeded", "11111111-1111-1111-1111-111111111111", map[string]any{"amount_cents": 500.0})
	data, err := json.Marshal(e)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := Parse(data)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if parsed.EventID != e.EventID || parsed.Payload["amount_cents"] != 500.0 || parsed.Version != 1 {
		t.Fatalf("round trip changed the event: %+v", parsed)
	}
}

func TestParseAcceptsPythonTimestamps(t *testing.T) {
	data := []byte(`{"event_id":"11111111-1111-1111-1111-111111111111","event_type":"X",
		"order_id":"22222222-2222-2222-2222-222222222222",
		"occurred_at":"2026-11-19T10:00:00.123456+00:00","version":1,"payload":{}}`)
	if _, err := Parse(data); err != nil {
		t.Fatalf("python isoformat timestamps must parse: %v", err)
	}
}

func TestParseRejectsMalformedMessages(t *testing.T) {
	for name, data := range map[string]string{
		"not json":     `nope`,
		"bad event id": `{"event_id":"x","event_type":"X","order_id":"22222222-2222-2222-2222-222222222222"}`,
		"no type":      `{"event_id":"11111111-1111-1111-1111-111111111111","order_id":"22222222-2222-2222-2222-222222222222"}`,
	} {
		if _, err := Parse([]byte(data)); !errors.Is(err, ErrMalformed) {
			t.Errorf("%s: want ErrMalformed, got %v", name, err)
		}
	}
}
