// Package db opens the Postgres pool and applies the embedded migrations.
package db

import (
	"context"
	"database/sql"
	"embed"
	"fmt"
	"io/fs"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	_ "github.com/jackc/pgx/v5/stdlib" // registers the "pgx" driver for goose
	"github.com/pressly/goose/v3"
)

//go:embed migrations/*.sql
var migrations embed.FS

// NewPool opens a small connection pool with connect and statement timeouts.
func NewPool(ctx context.Context, url string) (*pgxpool.Pool, error) {
	poolConfig, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, fmt.Errorf("parse DATABASE_URL: %w", err)
	}
	poolConfig.MaxConns = 5
	poolConfig.ConnConfig.ConnectTimeout = 3 * time.Second
	poolConfig.ConnConfig.RuntimeParams["statement_timeout"] = "5000"
	return pgxpool.NewWithConfig(ctx, poolConfig)
}

// Migrate applies every migration that has not run yet.
func Migrate(ctx context.Context, url string) error {
	conn, err := sql.Open("pgx", url)
	if err != nil {
		return err
	}
	defer conn.Close()
	files, err := fs.Sub(migrations, "migrations")
	if err != nil {
		return err
	}
	provider, err := goose.NewProvider(goose.DialectPostgres, conn, files)
	if err != nil {
		return err
	}
	results, err := provider.Up(ctx)
	for _, result := range results {
		slog.Info("migration applied", "version", result.Source.Version)
	}
	return err
}
