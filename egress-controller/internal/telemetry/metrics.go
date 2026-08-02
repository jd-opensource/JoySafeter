package telemetry

import (
	"github.com/prometheus/client_golang/prometheus"
)

type Metrics struct {
	XDSStreams         *prometheus.GaugeVec
	XDSRequests        *prometheus.CounterVec
	XDSResponses       *prometheus.CounterVec
	XDSACKs            *prometheus.CounterVec
	Snapshots          *prometheus.CounterVec
	SnapshotGeneration prometheus.Gauge
	ConnectedNodes     prometheus.Gauge
	Reconcile          *prometheus.CounterVec
	SourceEvents       *prometheus.CounterVec
	StatusEvents       *prometheus.CounterVec
	StatusQueueDepth   prometheus.Gauge
}

func New(registry prometheus.Registerer) *Metrics {
	metrics := &Metrics{
		XDSStreams: prometheus.NewGaugeVec(prometheus.GaugeOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "xds_streams",
			Help: "Current xDS streams by protocol.",
		}, []string{"protocol"}),
		XDSRequests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "xds_requests_total",
			Help: "xDS requests by protocol and resource type.",
		}, []string{"protocol", "type"}),
		XDSResponses: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "xds_responses_total",
			Help: "xDS responses by protocol and resource type.",
		}, []string{"protocol", "type"}),
		XDSACKs: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "xds_ack_total",
			Help: "xDS ACK and NACK outcomes by resource type.",
		}, []string{"result", "type"}),
		Snapshots: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "snapshots_total",
			Help: "Snapshot lifecycle operations.",
		}, []string{"result"}),
		SnapshotGeneration: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "highest_snapshot_generation",
			Help: "Highest candidate generation observed by this controller process.",
		}),
		ConnectedNodes: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "connected_nodes",
			Help: "Unique Envoy node identities with an active xDS stream.",
		}),
		Reconcile: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "reconcile_total",
			Help: "Snapshot source reconciliation outcomes.",
		}, []string{"result"}),
		SourceEvents: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "source_events_total",
			Help: "Desired-state source listener and notification outcomes.",
		}, []string{"kind", "result"}),
		StatusEvents: prometheus.NewCounterVec(prometheus.CounterOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "status_events_total",
			Help: "Durable status event outcomes.",
		}, []string{"kind", "result"}),
		StatusQueueDepth: prometheus.NewGauge(prometheus.GaugeOpts{
			Namespace: "joysafeter", Subsystem: "egress_controller", Name: "status_queue_depth",
			Help: "Pending durable status events in the local bounded queue.",
		}),
	}
	registry.MustRegister(
		metrics.XDSStreams, metrics.XDSRequests, metrics.XDSResponses, metrics.XDSACKs,
		metrics.Snapshots, metrics.SnapshotGeneration, metrics.ConnectedNodes, metrics.Reconcile,
		metrics.SourceEvents, metrics.StatusEvents, metrics.StatusQueueDepth,
	)
	return metrics
}
