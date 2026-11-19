package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func get(t *testing.T, server *http.Server, path string) (int, map[string]any) {
	t.Helper()
	recorder := httptest.NewRecorder()
	server.Handler.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, path, nil))
	var body map[string]any
	if err := json.Unmarshal(recorder.Body.Bytes(), &body); err != nil {
		t.Fatalf("bad json: %v", err)
	}
	return recorder.Code, body
}

func TestHealthzNeverChecksDependencies(t *testing.T) {
	server := NewServer(":0", map[string]Check{"postgres": func(context.Context) bool { return false }})
	code, body := get(t, server, "/healthz")
	if code != http.StatusOK || body["status"] != "ok" {
		t.Fatalf("got %d %v", code, body)
	}
}

func TestReadyzIs503WhenAnyCheckFails(t *testing.T) {
	server := NewServer(":0", map[string]Check{
		"postgres": func(context.Context) bool { return true },
		"consumer": func(context.Context) bool { return false },
	})
	code, body := get(t, server, "/readyz")
	if code != http.StatusServiceUnavailable || body["postgres"] != true || body["consumer"] != false {
		t.Fatalf("got %d %v", code, body)
	}
}

func TestServerHasTimeouts(t *testing.T) {
	server := NewServer(":0", nil)
	if server.ReadTimeout == 0 || server.WriteTimeout == 0 || server.IdleTimeout == 0 {
		t.Fatal("every server timeout must be set")
	}
}
