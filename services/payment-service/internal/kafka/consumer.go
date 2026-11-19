// Package kafka consumes events with manual offset commits.
//
// An offset is committed only after the handler succeeded (its transaction committed). If
// the service stops in between, Kafka delivers the message again and the handler's
// processed_events check skips it.
package kafka

import (
	"context"
	"errors"
	"log/slog"
	"sync/atomic"
	"time"

	"github.com/twmb/franz-go/pkg/kgo"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/events"
)

// Handler processes 1 event. A returned error means "try this message again later".
type Handler func(ctx context.Context, e events.Envelope) error

const (
	pollTimeout   = 2 * time.Second
	stalePoll     = 30 * time.Second
	maxBackoff    = 30 * time.Second
	commitTimeout = 10 * time.Second
)

// Consumer reads topics as 1 consumer group member.
type Consumer struct {
	client   *kgo.Client
	handler  Handler
	lastPoll atomic.Int64
}

// New connects to Kafka. Nothing is read until Run is called.
func New(brokers []string, group string, topics []string, handler Handler) (*Consumer, error) {
	client, err := kgo.NewClient(
		kgo.SeedBrokers(brokers...),
		kgo.ConsumerGroup(group),
		kgo.ConsumeTopics(topics...),
		kgo.DisableAutoCommit(),
		kgo.ConsumeResetOffset(kgo.NewOffset().AtStart()),
		kgo.DialTimeout(5*time.Second),
	)
	if err != nil {
		return nil, err
	}
	c := &Consumer{client: client, handler: handler}
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
		fetches.EachRecord(func(record *kgo.Record) { c.process(ctx, record) })
	}
}

func (c *Consumer) process(ctx context.Context, record *kgo.Record) {
	where := []any{"topic", record.Topic, "partition", record.Partition, "offset", record.Offset}
	envelope, err := events.Parse(record.Value)
	if err != nil {
		// M8 sends these to the .dlq topic. Until then: log loudly and move on.
		slog.Error("skipping a message that is not a valid event", append(where, "error", err)...)
		c.commit(ctx, record)
		return
	}
	wait := time.Second
	for {
		err := c.handler(ctx, envelope)
		if err == nil {
			c.commit(ctx, record)
			return
		}
		slog.Error("handling failed; will try again",
			append(where, "event_id", envelope.EventID, "retry_in", wait.String(), "error", err)...)
		select {
		case <-time.After(wait):
		case <-ctx.Done():
			return // not committed: read again after restart
		}
		c.lastPoll.Store(time.Now().UnixNano())
		wait = min(wait*2, maxBackoff)
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
