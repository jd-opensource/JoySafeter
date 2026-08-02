package source

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/joysafeter/joysafeter/egress-controller/internal/snapshot"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/joysafeter/joysafeter/egress-controller/internal/xds"
)

type FileReconciler struct {
	path       string
	maxBytes   int64
	interval   time.Duration
	publisher  Publisher
	logger     *slog.Logger
	metrics    *telemetry.Metrics
	mu         sync.Mutex
	lastDigest [sha256.Size]byte
	hasDigest  bool
}

type Publisher interface {
	Publish(context.Context, snapshot.Compiled) error
}

type Restorer interface {
	Restore(context.Context, snapshot.Compiled) error
}

func NewFileReconciler(path string, maxBytes int64, interval time.Duration, publisher Publisher, logger *slog.Logger, metrics *telemetry.Metrics) *FileReconciler {
	return &FileReconciler{path: path, maxBytes: maxBytes, interval: interval, publisher: publisher, logger: logger, metrics: metrics}
}

func (r *FileReconciler) Initial(ctx context.Context) error {
	changed, err := r.reconcile(ctx)
	if err != nil {
		r.metrics.Reconcile.WithLabelValues("error").Inc()
		return err
	}
	if changed {
		r.metrics.Reconcile.WithLabelValues("applied").Inc()
	} else {
		r.metrics.Reconcile.WithLabelValues("unchanged").Inc()
	}
	return nil
}

func (r *FileReconciler) Run(ctx context.Context) {
	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			changed, err := r.reconcile(ctx)
			if err != nil {
				r.metrics.Reconcile.WithLabelValues("error").Inc()
				r.logger.Error("snapshot reconciliation failed; retaining active snapshots", "error", err)
				continue
			}
			if changed {
				r.metrics.Reconcile.WithLabelValues("applied").Inc()
			} else {
				r.metrics.Reconcile.WithLabelValues("unchanged").Inc()
			}
		}
	}
}

func (r *FileReconciler) reconcile(ctx context.Context) (bool, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	data, err := os.ReadFile(r.path)
	if err != nil {
		return false, fmt.Errorf("read snapshot source: %w", err)
	}
	if int64(len(data)) > r.maxBytes {
		return false, fmt.Errorf("snapshot source exceeds %d bytes", r.maxBytes)
	}
	digest := sha256.Sum256(data)
	if r.hasDigest && digest == r.lastDigest {
		return false, nil
	}
	bundle, err := snapshot.ReadFile(r.path, r.maxBytes)
	if err != nil {
		return false, err
	}
	compiled, err := snapshot.Compile(bundle)
	if err != nil {
		return false, err
	}
	for _, candidate := range compiled {
		if err := r.publisher.Publish(ctx, candidate); err != nil {
			if errors.Is(err, xds.ErrRejectedVersion) {
				return false, fmt.Errorf("candidate %s remains rejected: %w", candidate.Version, err)
			}
			return false, err
		}
	}
	r.lastDigest = digest
	r.hasDigest = true
	r.logger.Info("snapshot source reconciled", "groups", len(compiled), "digest", fmt.Sprintf("%x", digest[:8]))
	return true, nil
}
