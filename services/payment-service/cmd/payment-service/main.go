// Command payment-service charges and refunds orders through a fake payment provider.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/config"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/db"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/httpapi"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/kafka"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/payments"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/provider"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service", "payment-service")
	slog.SetDefault(logger)
	if err := run(); err != nil {
		logger.Error("payment-service stopped with an error", "error", err)
		os.Exit(1)
	}
}

func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// "payment-service healthcheck" is the container health check (the image has no shell).
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		return healthcheck(ctx)
	}
	// "payment-service migrate" applies migrations and exits (used by payment-migrate).
	if len(os.Args) > 1 && os.Args[1] == "migrate" {
		url := os.Getenv("DATABASE_URL")
		if url == "" {
			return errors.New("DATABASE_URL is required")
		}
		return db.Migrate(ctx, url)
	}

	cfg, err := config.FromEnv()
	if err != nil {
		return err
	}
	pool, err := db.NewPool(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	defer pool.Close()

	fake := provider.NewFake(cfg.FailureRate, cfg.ProviderDelay)
	service := payments.New(pool, fake, cfg.ProviderTimeout, cfg.ProviderAttempts)
	consumer, err := kafka.New(cfg.KafkaBrokers, "payment-service", []string{"orders.events"}, service.Handle)
	if err != nil {
		return err
	}
	consumerDone := make(chan struct{})
	go func() {
		defer close(consumerDone)
		consumer.Run(ctx)
	}()
	slog.Info("payment-service started",
		"failure_rate", cfg.FailureRate, "provider_delay", cfg.ProviderDelay.String())

	server := httpapi.NewServer(cfg.HTTPAddr, map[string]httpapi.Check{
		"postgres": func(ctx context.Context) bool { return pool.Ping(ctx) == nil },
		"consumer": consumer.Healthy,
	})
	err = serve(ctx, server)
	stop()
	<-consumerDone
	return err
}

func healthcheck(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://localhost:8003/readyz", nil)
	if err != nil {
		return err
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("not ready: %s", response.Status)
	}
	return nil
}

// serve runs the HTTP server until ctx is cancelled, then shuts it down gracefully.
func serve(ctx context.Context, server *http.Server) error {
	errs := make(chan error, 1)
	go func() {
		slog.Info("http server listening", "addr", server.Addr)
		errs <- server.ListenAndServe()
	}()
	select {
	case err := <-errs:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		return server.Shutdown(shutdownCtx)
	}
}
