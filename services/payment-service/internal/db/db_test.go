package db

import (
	"context"
	"testing"

	"github.com/jackc/pgx/v5"

	"github.com/keshan-dev/orderflow/services/payment-service/internal/testdb"
)

func TestMigrateCreatesTablesAndOneChargePerOrder(t *testing.T) {
	ctx := context.Background()
	url := testdb.New(t)
	if err := Migrate(ctx, url); err != nil {
		t.Fatalf("migrate: %v", err)
	}
	if err := Migrate(ctx, url); err != nil {
		t.Fatalf("second migrate should be a no-op: %v", err)
	}
	conn, err := pgx.Connect(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close(ctx)

	insert := `INSERT INTO payments (id, order_id, amount_cents, status)
	           VALUES (gen_random_uuid(), '00000000-0000-0000-0000-000000000001', 100, $1)`
	for _, status := range []string{"FAILED", "FAILED", "SUCCEEDED"} {
		if _, err := conn.Exec(ctx, insert, status); err != nil {
			t.Fatalf("insert %s: %v", status, err)
		}
	}
	if _, err := conn.Exec(ctx, insert, "SUCCEEDED"); err == nil {
		t.Fatal("a second successful charge for the same order must be rejected")
	}
}
