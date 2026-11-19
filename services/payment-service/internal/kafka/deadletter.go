package kafka

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/twmb/franz-go/pkg/kgo"
)

// Header names, shared with the Python services (orderflow_common.deadletter).
const (
	headerOriginalTopic = "x-original-topic"
	headerGroup         = "x-consumer-group"
	headerAttempt       = "x-attempt"
	headerError         = "x-error"
	headerNextTryAt     = "x-next-try-at-ms"

	retrySuffix      = ".retry"
	dlqSuffix        = ".dlq"
	maxErrorLength   = 500
	MaxRetryAttempts = 5
)

// retryDelay is 2, 4, 8, 16, 32 seconds, capped at 60.
func retryDelay(attempt int) time.Duration {
	return min(time.Duration(1<<attempt)*time.Second, 60*time.Second)
}

// retryInfo is what the retry and dead letter headers say about a record.
type retryInfo struct {
	originalTopic string
	group         string
	attempt       int
	nextTryAt     time.Time
}

func readRetryInfo(record *kgo.Record) (retryInfo, bool) {
	headers := map[string]string{}
	for _, h := range record.Headers {
		headers[h.Key] = string(h.Value)
	}
	group, ok := headers[headerGroup]
	if !ok {
		return retryInfo{}, false
	}
	attempt, _ := strconv.Atoi(headers[headerAttempt])
	nextMs, _ := strconv.ParseInt(headers[headerNextTryAt], 10, 64)
	return retryInfo{
		originalTopic: headers[headerOriginalTopic],
		group:         group,
		attempt:       attempt,
		nextTryAt:     time.UnixMilli(nextMs),
	}, true
}

// publishAside copies record to <originalTopic>.retry or <originalTopic>.dlq and waits for
// the broker to confirm it.
func publishAside(ctx context.Context, client *kgo.Client, suffix, originalTopic, group string,
	attempt int, record *kgo.Record, cause error) error {
	var due int64
	if suffix == retrySuffix {
		due = time.Now().Add(retryDelay(attempt)).UnixMilli()
	}
	message := cause.Error()
	if len(message) > maxErrorLength {
		message = message[:maxErrorLength]
	}
	aside := &kgo.Record{
		Topic: originalTopic + suffix,
		Key:   record.Key,
		Value: record.Value,
		Headers: []kgo.RecordHeader{
			{Key: headerOriginalTopic, Value: []byte(originalTopic)},
			{Key: headerGroup, Value: []byte(group)},
			{Key: headerAttempt, Value: []byte(strconv.Itoa(attempt))},
			{Key: headerError, Value: []byte(message)},
			{Key: headerNextTryAt, Value: []byte(strconv.FormatInt(due, 10))},
		},
	}
	produceCtx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	if err := client.ProduceSync(produceCtx, aside).FirstErr(); err != nil {
		return fmt.Errorf("publish to %s: %w", aside.Topic, err)
	}
	return nil
}
