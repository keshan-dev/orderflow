// Package kafka consumes events with manual offset commits.
//
// An offset is committed only after the handler succeeded (its transaction committed), or
// after the message was safely moved to a retry or dead letter topic. If the service stops
// in between, Kafka delivers the message again and the handler's processed_events check
// skips it.
//
// When the handler keeps failing:
//   - a temporary failure goes to <topic>.retry and is tried again later by a second
//     consumer (group "<group>.retry"), with a growing delay, up to MaxRetryAttempts times;
//   - a malformed message, or too many attempts, goes to <topic>.dlq.
//
// Every retry and dead letter message carries the consumer group that failed it, because
// several groups read the same topic; other groups skip it.
package kafka

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"

	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/events"
)

// Handler processes 1 event. A returned error means "this attempt failed".
type Handler func(ctx context.Context, e events.Envelope) error

const (
	pollTimeout    = 2 * time.Second
	stalePoll      = 30 * time.Second
	maxBackoff     = 30 * time.Second
	commitTimeout  = 10 * time.Second
	quickAttempts  = 3
	quickRetryWait = 200 * time.Millisecond
)

// Consumer reads topics as 1 consumer group member.
type Consumer struct {
	client   *kgo.Client
	handler  Handler
	group    string // the group whose failures this consumer owns (main group name)
	isRetry  bool
	lastPoll atomic.Int64
}

// New returns the consumer of the main topics, in consumer group `group`.
func New(brokers []string, group string, topics []string, handler Handler) (*Consumer, error) {
	return newConsumer(brokers, group, group, topics, handler, false)
}

// NewRetry returns the consumer of the retry topics for `group`. It runs in its own consumer
// group, so waiting for a retry to be due never blocks the main topics.
func NewRetry(brokers []string, group string, topics []string, handler Handler) (*Consumer, error) {
	retryTopics := make([]string, len(topics))
	for i, topic := range topics {
		retryTopics[i] = topic + retrySuffix
	}
	return newConsumer(brokers, group+retrySuffix, group, retryTopics, handler, true)
}

func newConsumer(brokers []string, groupID, owner string, topics []string, handler Handler,
	isRetry bool) (*Consumer, error) {
	client, err := kgo.NewClient(
		kgo.SeedBrokers(brokers...),
		kgo.ConsumerGroup(groupID),
		kgo.ConsumeTopics(topics...),
		kgo.DisableAutoCommit(),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()),
		kgo.DialTimeout(5*time.Second),
		kgo.RequiredAcks(kgo.AllISRAcks()),
	)
	if err != nil {
		return nil, err
	}
	c := &Consumer{client: client, handler: handler, group: owner, isRetry: isRetry}
	c.lastPoll.Store(time.Now().UnixNano())
	return c, nil
}

// Healthy is false when the poll loop has stopped or is stuck.
func (c *Consumer) Healthy(context.Context) bool {
	return time.Since(time.Unix(0, c.lastPoll.Load())) < stalePoll
}

// Run polls until ctx is cancelled, then closes the client.
func (c *Consumer) Run(ctx context.Context) {
	defer c.client.Close()
	for ctx.Err() == nil {
		pollCtx, cancel := context.WithTimeout(ctx, pollTimeout)
		fetches := c.client.PollFetches(pollCtx)
		cancel()
		c.lastPoll.Store(time.Now().UnixNano())
		if fetches.IsClientClosed() {
			return
		}
		fetches.EachError(func(topic string, partition int32, err error) {
			if !errors.Is(err, context.DeadlineExceeded) && !errors.Is(err, context.Canceled) {
				slog.Warn("kafka fetch error", "topic", topic, "partition", partition, "error", err)
			}
		})
		fetches.EachRecord(func(record *kgo.Record) {
			if ctx.Err() == nil {
				c.process(ctx, record)
			}
		})
	}
}

func (c *Consumer) process(ctx context.Context, record *kgo.Record) {
	originalTopic, attempt := record.Topic, 0
	if c.isRetry {
		info, ok := readRetryInfo(record)
		if !ok || info.group != c.group {
			c.commit(ctx, record) // another group's retry: not ours
			return
		}
		if !c.waitUntil(ctx, info.nextTryAt) {
			return // shutting down: not committed, read again after restart
		}
		originalTopic = info.originalTopic
		if originalTopic == "" {
			originalTopic = strings.TrimSuffix(record.Topic, retrySuffix)
		}
		attempt = info.attempt
	}
	where := []any{"topic", record.Topic, "partition", record.Partition, "offset", record.Offset}

	envelope, err := events.Parse(record.Value)
	if err != nil {
		slog.Error("not a valid event; sending it to the dead letter topic", append(where, "error", err)...)
		c.moveAside(ctx, record, dlqSuffix, originalTopic, attempt, err)
		return
	}
	if err := c.handleWithQuickRetries(ctx, envelope); err != nil {
		if ctx.Err() != nil {
			return
		}
		if attempt+1 > MaxRetryAttempts {
			slog.Error("event failed too many times; sending it to the dead letter topic",
				append(where, "event_id", envelope.EventID, "attempt", attempt, "error", err)...)
			c.moveAside(ctx, record, dlqSuffix, originalTopic, attempt, err)
		} else {
			slog.Warn("event failed; it will be tried again from the retry topic",
				append(where, "event_id", envelope.EventID, "attempt", attempt+1, "error", err)...)
			c.moveAside(ctx, record, retrySuffix, originalTopic, attempt+1, err)
		}
		return
	}
	c.commit(ctx, record)
}

func (c *Consumer) handleWithQuickRetries(ctx context.Context, envelope events.Envelope) error {
	var err error
	for try := 1; try <= quickAttempts; try++ {
		if err = c.handler(ctx, envelope); err == nil {
			return nil
		}
		if try < quickAttempts && !sleep(ctx, quickRetryWait*time.Duration(try)) {
			return ctx.Err()
		}
	}
	return err
}

// moveAside publishes the record to a retry or dead letter topic and then commits it. If
// publishing fails, it keeps trying (with a growing wait) instead of losing the record.
func (c *Consumer) moveAside(ctx context.Context, record *kgo.Record, suffix, originalTopic string,
	attempt int, cause error) {
	wait := time.Second
	for {
		err := publishAside(ctx, c.client, suffix, originalTopic, c.group, attempt, record, cause)
		if err == nil {
			c.commit(ctx, record)
			return
		}
		slog.Error("could not move the message aside; trying again", "error", err, "retry_in", wait.String())
		if !sleep(ctx, wait) {
			return
		}
		c.lastPoll.Store(time.Now().UnixNano())
		wait = min(wait*2, maxBackoff)
	}
}

// waitUntil sleeps until `due`, keeping the health signal fresh. False means ctx ended.
func (c *Consumer) waitUntil(ctx context.Context, due time.Time) bool {
	for {
		left := time.Until(due)
		if left <= 0 {
			return true
		}
		if !sleep(ctx, min(left, 5*time.Second)) {
			return false
		}
		c.lastPoll.Store(time.Now().UnixNano())
	}
}

func (c *Consumer) commit(ctx context.Context, record *kgo.Record) {
	commitCtx, cancel := context.WithTimeout(ctx, commitTimeout)
	defer cancel()
	if err := c.client.CommitRecords(commitCtx, record); err != nil {
		// The message may come again; the handler's duplicate check makes that safe.
		slog.Warn("offset commit failed", "error", err)
	}
}

func sleep(ctx context.Context, d time.Duration) bool {
	select {
	case <-time.After(d):
		return true
	case <-ctx.Done():
		return false
	}
}
