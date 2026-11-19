package config

import (
	"testing"
	"time"
)

func TestFromEnvReadsValuesAndDefaults(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgresql://u:p@db/payments_db")
	t.Setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092,kafka2:19092")
	t.Setenv("PAYMENT_FAILURE_RATE", "0.25")
	t.Setenv("PAYMENT_DELAY_MS", "0")

	cfg, err := FromEnv()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.KafkaBrokers) != 2 || cfg.FailureRate != 0.25 || cfg.ProviderDelay != 0 {
		t.Fatalf("unexpected config: %+v", cfg)
	}
	if cfg.HTTPAddr != ":8003" || cfg.ProviderTimeout != 2*time.Second || cfg.ProviderAttempts != 3 {
		t.Fatalf("defaults not applied: %+v", cfg)
	}
}

func TestFromEnvRejectsBadValues(t *testing.T) {
	t.Setenv("DATABASE_URL", "postgresql://x")
	t.Setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:19092")
	for name, value := range map[string]string{
		"PAYMENT_FAILURE_RATE": "1.5",
		"PAYMENT_DELAY_MS":     "-1",
		"PROVIDER_ATTEMPTS":    "0",
	} {
		t.Run(name, func(t *testing.T) {
			t.Setenv(name, value)
			if _, err := FromEnv(); err == nil {
				t.Fatalf("%s=%s should be rejected", name, value)
			}
		})
	}
}

func TestFromEnvRequiresDatabaseURL(t *testing.T) {
	t.Setenv("DATABASE_URL", "")
	if _, err := FromEnv(); err == nil {
		t.Fatal("missing DATABASE_URL should be rejected")
	}
}
