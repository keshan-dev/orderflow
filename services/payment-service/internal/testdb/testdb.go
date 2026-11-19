// Package testdb gives integration tests a fresh, empty database on the Compose Postgres.
// Tests are skipped when that Postgres is not running.
package testdb

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

const hostPort = "127.0.0.1:15432"

// New creates an empty database, drops it when the test ends, and returns its URL.
func New(t *testing.T) string {
	t.Helper()
	conn, err := net.DialTimeout("tcp", hostPort, time.Second)
	if err != nil {
		t.Skip("Compose Postgres is not running on " + hostPort)
	}
	_ = conn.Close()

	password := composePassword(t)
	admin := fmt.Sprintf("postgresql://postgres:%s@%s/postgres?connect_timeout=5", password, hostPort)
	name := fmt.Sprintf("payments_test_%d", time.Now().UnixNano())
	ctx := context.Background()
	adminConn, err := pgx.Connect(ctx, admin)
	if err != nil {
		t.Fatalf("connect as admin: %v", err)
	}
	if _, err := adminConn.Exec(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatalf("create database: %v", err)
	}
	_ = adminConn.Close(ctx)

	t.Cleanup(func() {
		c, err := pgx.Connect(ctx, admin)
		if err != nil {
			return
		}
		defer c.Close(ctx)
		_, _ = c.Exec(ctx, "DROP DATABASE IF EXISTS "+name+" WITH (FORCE)")
	})
	return fmt.Sprintf("postgresql://postgres:%s@%s/%s?connect_timeout=5", password, hostPort, name)
}

// composePassword reads POSTGRES_PASSWORD from deploy/compose/.env.
func composePassword(t *testing.T) string {
	t.Helper()
	dir, _ := os.Getwd()
	for range 6 {
		path := filepath.Join(dir, "deploy", "compose", ".env")
		if file, err := os.Open(path); err == nil {
			defer file.Close()
			scanner := bufio.NewScanner(file)
			for scanner.Scan() {
				if value, ok := strings.CutPrefix(scanner.Text(), "POSTGRES_PASSWORD="); ok {
					return strings.TrimSpace(value)
				}
			}
		}
		dir = filepath.Dir(dir)
	}
	t.Skip("deploy/compose/.env not found")
	return ""
}
