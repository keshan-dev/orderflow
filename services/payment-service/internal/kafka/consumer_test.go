package kafka

import (
	"context"
	"errors"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/twmb/franz-go/pkg/kadm"
	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/events"
)

const broker = "127.0.0.1:29092"

// throwawayTopic creates <name>, <name>.retry and <name>.dlq on the Compose broker.
func throwawayTopic(t *testing.T) string {
	t.Helper()
	if conn, err := net.DialTimeout("tcp", broker, time.Second); err != nil {
		t.Skip("Compose Kafka is not running")
	} else {
		_ = conn.Close()
	}
	client, err := kgo.NewClient(kgo.SeedBrokers(broker))
	if err != nil {
		t.Fatal(err)
	}
	admin := kadm.NewClient(client)
	name := "test.go." + uuid.NewString()[:8]
	names := []string{name, name + retrySuffix, name + dlqSuffix}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if _, err := admin.CreateTopics(ctx, 1, 1, nil, names...); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		_, _ = admin.DeleteTopics(ctx, names...)
		client.Close()
	})
	return name
}

func produce(t *testing.T, topic string, value []byte, headers ...kgo.RecordHeader) {
	t.Helper()
	client, err := kgo.NewClient(kgo.SeedBrokers(broker))
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	record := &kgo.Record{Topic: topic, Value: value, Headers: headers}
	if err := client.ProduceSync(ctx, record).FirstErr(); err != nil {
		t.Fatal(err)
	}
}

func readAll(t *testing.T, topic string) []*kgo.Record {
	t.Helper()
	client, err := kgo.NewClient(kgo.SeedBrokers(broker), kgo.ConsumeTopics(topic),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()))
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	var records []*kgo.Record
	for range 3 {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		client.PollFetches(ctx).EachRecord(func(r *kgo.Record) { records = append(records, r) })
		cancel()
	}
	return records
}

func eventBytes(t *testing.T) []byte {
	t.Helper()
	return []byte(`{"event_id":"` + uuid.NewString() + `","event_type":"ChargePaymentRequested",` +
		`"order_id":"` + uuid.NewString() + `","occurred_at":"2026-11-19T10:00:00Z","version":1,"payload":{}}`)
}

func waitFor(t *testing.T, timeout time.Duration, condition func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if condition() {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}
	t.Fatal("condition not met in time")
}

func run(t *testing.T, group, topic string, handler Handler) context.CancelFunc {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	for _, build := range []func([]string, string, []string, Handler) (*Consumer, error){New, NewRetry} {
		c, err := build([]string{broker}, group, []string{topic}, handler)
		if err != nil {
			t.Fatal(err)
		}
		go c.Run(ctx)
	}
	return cancel
}

func header(r *kgo.Record, key string) string {
	for _, h := range r.Headers {
		if h.Key == key {
			return string(h.Value)
		}
	}
	return ""
}

func TestMalformedMessageGoesToTheDLQ(t *testing.T) {
	topic := throwawayTopic(t)
	group := "g-" + uuid.NewString()[:6]
	produce(t, topic, []byte("not json"))
	stop := run(t, group, topic, func(context.Context, events.Envelope) error { return nil })
	defer stop()
	waitFor(t, 20*time.Second, func() bool { return len(readAll(t, topic+dlqSuffix)) == 1 })
	if got := header(readAll(t, topic+dlqSuffix)[0], headerGroup); got != group {
		t.Fatalf("dead letter group header = %q", got)
	}
}

func TestFailingHandlerIsRetriedFromTheRetryTopic(t *testing.T) {
	topic := throwawayTopic(t)
	var calls atomic.Int32
	produce(t, topic, eventBytes(t))
	stop := run(t, "g-"+uuid.NewString()[:6], topic, func(context.Context, events.Envelope) error {
		if calls.Add(1) <= quickAttempts { // every quick attempt fails
			return errors.New("database down")
		}
		return nil
	})
	defer stop()
	waitFor(t, 30*time.Second, func() bool { return calls.Load() == quickAttempts+1 })
	if retried := readAll(t, topic+retrySuffix); len(retried) != 1 || header(retried[0], headerAttempt) != "1" {
		t.Fatalf("want 1 retry message with attempt 1, got %d", len(retried))
	}
	if dead := readAll(t, topic+dlqSuffix); len(dead) != 0 {
		t.Fatal("nothing should reach the dead letter topic")
	}
}

func TestRetryOfAnotherGroupIsIgnored(t *testing.T) {
	topic := throwawayTopic(t)
	var calls atomic.Int32
	produce(t, topic+retrySuffix, eventBytes(t),
		kgo.RecordHeader{Key: headerGroup, Value: []byte("some-other-group")},
		kgo.RecordHeader{Key: headerAttempt, Value: []byte("1")})
	stop := run(t, "g-"+uuid.NewString()[:6], topic, func(context.Context, events.Envelope) error {
		calls.Add(1)
		return nil
	})
	defer stop()
	time.Sleep(6 * time.Second)
	if calls.Load() != 0 {
		t.Fatal("another group's retry must not be handled")
	}
}
