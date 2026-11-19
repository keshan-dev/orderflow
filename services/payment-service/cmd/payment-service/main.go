// Command payment-service charges and refunds orders through a fake payment provider.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/config"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/db"
	"github.com/keshan-dev/orderflow/services/payment-service/internal/httpapi"
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

	server := httpapi.NewServer(cfg.HTTPAddr, map[string]httpapi.Check{
		"postgres": func(ctx context.Context) bool { return pool.Ping(ctx) == nil },
	})
	return serve(ctx, server)
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
