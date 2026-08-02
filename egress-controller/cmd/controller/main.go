package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	logv3 "github.com/envoyproxy/go-control-plane/pkg/log"
	compilerpkg "github.com/joysafeter/joysafeter/egress-controller/internal/compiler"
	"github.com/joysafeter/joysafeter/egress-controller/internal/config"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/health"
	"github.com/joysafeter/joysafeter/egress-controller/internal/source"
	"github.com/joysafeter/joysafeter/egress-controller/internal/status"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
	"github.com/joysafeter/joysafeter/egress-controller/internal/xds"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
)

var (
	version = "dev"
	commit  = "unknown"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		address := os.Getenv("JOYSAFETER_EGRESS_CONTROLLER_HTTP_ADDR")
		if address == "" {
			address = ":18080"
		}
		_, port, err := net.SplitHostPort(address)
		if err != nil {
			os.Exit(1)
		}
		client := &http.Client{Timeout: 2 * time.Second}
		response, err := client.Get("http://127.0.0.1:" + port + "/readyz")
		if err != nil || response.StatusCode != http.StatusOK {
			os.Exit(1)
		}
		_ = response.Body.Close()
		return
	}
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("load configuration: %w", err)
	}
	logger := newLogger(cfg.LogLevel)
	if !cfg.TLS.Enabled {
		logger.Warn("xDS mTLS is disabled; this is only acceptable for isolated development")
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	registry := prometheus.NewRegistry()
	registry.MustRegister(collectors.NewGoCollector(), collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}))
	metrics := telemetry.New(registry)
	var recorder status.Recorder = status.NopRecorder{}
	var postgresRecorder *status.PostgresRecorder
	if cfg.StateDatabaseURL != "" {
		postgresRecorder, err = status.NewPostgresRecorder(
			context.Background(), cfg.StateDatabaseURL, cfg.ControllerID, int(cfg.StatusQueueSize),
			cfg.NodeLeaseTTL, cfg.NodeHeartbeat, logger, metrics,
		)
		if err != nil {
			return err
		}
		recorder = postgresRecorder
		logger.Info("durable egress apply-status persistence enabled", "controller_instance", cfg.ControllerID)
	}
	cacheLogger := logv3.LoggerFuncs{
		DebugFunc: func(format string, args ...interface{}) { logger.Debug(fmt.Sprintf(format, args...)) },
		InfoFunc:  func(format string, args ...interface{}) { logger.Info(fmt.Sprintf(format, args...)) },
		WarnFunc:  func(format string, args ...interface{}) { logger.Warn(fmt.Sprintf(format, args...)) },
		ErrorFunc: func(format string, args ...interface{}) { logger.Error(fmt.Sprintf(format, args...)) },
	}
	snapshotCache := cachev3.NewSnapshotCache(true, group.Hasher{}, cacheLogger)
	manager := xds.NewManager(snapshotCache, logger, metrics, recorder)
	type reconciler interface {
		Initial(context.Context) error
		Run(context.Context)
	}
	var desiredState reconciler
	var postgresSource *source.PostgresReconciler
	if cfg.SourceMode == "postgres" {
		compilerConfig := compilerpkg.DefaultConfig()
		compilerConfig.CredentialAddress = cfg.CredentialAddress
		compilerConfig.CredentialPort = cfg.CredentialPort
		compilerConfig.ForwardAddress = cfg.ForwardAddress
		compilerConfig.ForwardPort = cfg.ForwardPort
		compilerConfig.AuthzHost = cfg.AuthzHost
		compilerConfig.AuthzPort = cfg.AuthzPort
		compilerConfig.AuthzTLS = cfg.AuthzTLS
		compilerConfig.AuthzServerName = cfg.AuthzServerName
		compilerConfig.AuthzClientCert = cfg.AuthzClientCert
		compilerConfig.AuthzClientKey = cfg.AuthzClientKey
		compilerConfig.AuthzCA = cfg.AuthzCA
		compilerConfig.DownstreamTLS = cfg.DownstreamTLS
		compilerConfig.DownstreamCert = cfg.DownstreamCert
		compilerConfig.DownstreamKey = cfg.DownstreamKey
		compilerConfig.PublicCA = cfg.PublicCA
		compilerConfig.SocketRoot = cfg.SocketRoot
		policyCompiler, err := compilerpkg.New(compilerConfig)
		if err != nil {
			return fmt.Errorf("configure policy compiler: %w", err)
		}
		postgresSource, err = source.NewPostgresReconciler(
			ctx, cfg.StateDatabaseURL, cfg.ReconcileInterval, policyCompiler, manager, logger, metrics,
		)
		if err != nil {
			return err
		}
		desiredState = postgresSource
	} else {
		desiredState = source.NewFileReconciler(
			cfg.SnapshotFile, cfg.MaxSnapshotBytes, cfg.ReconcileInterval, manager, logger, metrics,
		)
	}
	if err := desiredState.Initial(ctx); err != nil {
		if postgresSource != nil {
			postgresSource.Close()
		}
		if postgresRecorder != nil {
			closeContext, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = postgresRecorder.Close(closeContext)
		}
		return fmt.Errorf("initial snapshot reconciliation: %w", err)
	}

	callbacks := xds.NewCallbacks(manager, logger, metrics)
	grpcServer, err := xds.NewGRPCServer(ctx, snapshotCache, callbacks, cfg.TLS)
	if err != nil {
		return err
	}
	xdsListener, err := net.Listen("tcp", cfg.XDSAddress)
	if err != nil {
		return fmt.Errorf("listen for xDS: %w", err)
	}
	defer xdsListener.Close()
	httpListener, err := net.Listen("tcp", cfg.HTTPAddress)
	if err != nil {
		return fmt.Errorf("listen for health: %w", err)
	}
	defer httpListener.Close()

	healthState := &health.State{}
	httpServer := &http.Server{
		Handler: healthState.Handler(registry), ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout: 10 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second,
	}
	errorChannel := make(chan error, 2)
	reconcilerDone := make(chan struct{})
	go func() {
		defer close(reconcilerDone)
		desiredState.Run(ctx)
	}()
	go func() {
		if err := grpcServer.Serve(xdsListener); err != nil {
			errorChannel <- fmt.Errorf("serve xDS: %w", err)
		}
	}()
	go func() {
		if err := httpServer.Serve(httpListener); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errorChannel <- fmt.Errorf("serve health: %w", err)
		}
	}()
	healthState.SetReady(true)
	logger.Info("egress controller started", "version", version, "commit", commit, "xds_address", cfg.XDSAddress, "http_address", cfg.HTTPAddress, "mtls", cfg.TLS.Enabled)

	select {
	case <-ctx.Done():
	case err := <-errorChannel:
		stop()
		logger.Error("controller server failed", "error", err)
	}
	healthState.SetReady(false)
	shutdownContext, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	grpcStopped := make(chan struct{})
	go func() {
		grpcServer.GracefulStop()
		close(grpcStopped)
	}()
	select {
	case <-grpcStopped:
	case <-shutdownContext.Done():
		grpcServer.Stop()
	}
	if err := httpServer.Shutdown(shutdownContext); err != nil && !errors.Is(err, context.DeadlineExceeded) {
		logger.Error("HTTP shutdown failed", "error", err)
	}
	select {
	case <-reconcilerDone:
	case <-shutdownContext.Done():
		logger.Error("desired-state reconciler shutdown timed out")
	}
	if postgresSource != nil {
		postgresSource.Close()
	}
	if postgresRecorder != nil {
		if err := postgresRecorder.Close(shutdownContext); err != nil {
			logger.Error("status recorder shutdown failed", "error", err)
		}
	}
	logger.Info("egress controller stopped")
	return nil
}

func newLogger(level string) *slog.Logger {
	value := slog.LevelInfo
	switch level {
	case "debug":
		value = slog.LevelDebug
	case "warn":
		value = slog.LevelWarn
	case "error":
		value = slog.LevelError
	}
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: value}))
}
