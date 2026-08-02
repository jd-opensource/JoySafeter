// Mock upstream echo server for the Docker egress smoke (Plan 2 / C-2).
//
// It echoes every received request (method, path, headers, body) back as JSON
// AND logs the same document as a single stdout line. The smoke uses the
// response body to prove the platform credential header was injected by the
// egress boundary (and sandbox-supplied auth was stripped), and uses the stdout
// log to cross-correlate the Envoy-assigned x-request-id. No TLS, no secret,
// no external dependency: a pinned Go base builds it so CI never pulls a
// third-party echo image (which the daocloud mirror 403s).
package main

import (
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
)

type echo struct {
	Method  string              `json:"method"`
	Path    string              `json:"path"`
	Headers map[string][]string `json:"headers"`
	Body    string              `json:"body"`
}

func main() {
	port := os.Getenv("HTTP_PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// A liveness path the smoke can hit without polluting the echo log.
		if r.URL.Path == "/ping" {
			w.WriteHeader(http.StatusOK)
			_, _ = io.WriteString(w, "pong\n")
			return
		}
		body, _ := io.ReadAll(r.Body)
		doc := echo{
			Method:  r.Method,
			Path:    r.URL.Path,
			Headers: map[string][]string(r.Header),
			Body:    string(body),
		}
		out, err := json.Marshal(doc)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		// Single-line stdout log so the smoke can grep x-request-id.
		log.Printf("%s", out)
		w.Header().Set("content-type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(out)
	})

	log.SetFlags(0)
	log.Printf(`{"event":"listening","port":%q}`, port)
	srv := &http.Server{Addr: ":" + port, Handler: mux}
	if err := srv.ListenAndServe(); err != nil {
		log.Fatalf(`{"event":"exit","error":%q}`, err.Error())
	}
}
