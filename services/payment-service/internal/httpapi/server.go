// Package httpapi serves the health endpoints of payment-service.
package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"time"
)

// Check reports whether 1 dependency is usable right now.
type Check func(ctx context.Context) bool

const checkTimeout = 2 * time.Second

// NewServer returns an HTTP server with read, write and idle timeouts, so a slow or stuck
// client can never hold a connection forever.
func NewServer(addr string, checks map[string]Check) *http.Server {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), checkTimeout)
		defer cancel()
		results := make(map[string]bool, len(checks))
		status := http.StatusOK
		for name, check := range checks {
			results[name] = check(ctx)
			if !results[name] {
				status = http.StatusServiceUnavailable
			}
		}
		writeJSON(w, status, results)
	})
	return &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
