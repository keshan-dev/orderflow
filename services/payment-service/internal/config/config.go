// Package config reads payment-service settings from environment variables.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config holds every setting. All of them come from environment variables.
type Config struct {
	DatabaseURL      string
	KafkaBrokers     []string
	HTTPAddr         string
	FailureRate      float64       // share of charges the fake provider declines (0 to 1)
	ProviderDelay    time.Duration // how long the fake provider takes per call
	ProviderTimeout  time.Duration // deadline for 1 provider call
	ProviderAttempts int           // how many times 1 charge is tried before giving up
}

// FromEnv reads the configuration. It fails fast when a required value is missing or invalid.
func FromEnv() (Config, error) {
	cfg := Config{
		DatabaseURL: os.Getenv("DATABASE_URL"),
		HTTPAddr:    envOr("HTTP_ADDR", ":8003"),
	}
	if cfg.DatabaseURL == "" {
		return Config{}, fmt.Errorf("DATABASE_URL is required")
	}
	brokers := os.Getenv("KAFKA_BOOTSTRAP_SERVERS")
	if brokers == "" {
		return Config{}, fmt.Errorf("KAFKA_BOOTSTRAP_SERVERS is required")
	}
	cfg.KafkaBrokers = strings.Split(brokers, ",")

	var err error
	if cfg.FailureRate, err = floatEnv("PAYMENT_FAILURE_RATE", 0); err != nil {
		return Config{}, err
	}
	if cfg.FailureRate < 0 || cfg.FailureRate > 1 {
		return Config{}, fmt.Errorf("PAYMENT_FAILURE_RATE must be between 0 and 1")
	}
	if cfg.ProviderDelay, err = msEnv("PAYMENT_DELAY_MS", 50); err != nil {
		return Config{}, err
	}
	if cfg.ProviderTimeout, err = msEnv("PROVIDER_TIMEOUT_MS", 2000); err != nil {
		return Config{}, err
	}
	if cfg.ProviderAttempts, err = intEnv("PROVIDER_ATTEMPTS", 3); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func floatEnv(name string, fallback float64) (float64, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return 0, fmt.Errorf("%s must be a number: %w", name, err)
	}
	return value, nil
}

func intEnv(name string, fallback int) (int, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 1 {
		return 0, fmt.Errorf("%s must be a whole number of 1 or more", name)
	}
	return value, nil
}

func msEnv(name string, fallbackMs int) (time.Duration, error) {
	ms, err := intEnvAllowZero(name, fallbackMs)
	return time.Duration(ms) * time.Millisecond, err
}

func intEnvAllowZero(name string, fallback int) (int, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 0 {
		return 0, fmt.Errorf("%s must be a whole number of 0 or more", name)
	}
	return value, nil
}
