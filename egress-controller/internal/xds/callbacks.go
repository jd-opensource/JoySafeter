package xds

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"sync"

	corev3 "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	discoveryv3 "github.com/envoyproxy/go-control-plane/envoy/service/discovery/v3"
	serverv3 "github.com/envoyproxy/go-control-plane/pkg/server/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"github.com/joysafeter/joysafeter/egress-controller/internal/telemetry"
)

type Callbacks struct {
	serverv3.CallbackFuncs
	mu         sync.Mutex
	streams    map[streamKey]group.Identity
	deliveries map[deliveryKey]delivery
	manager    *Manager
	logger     *slog.Logger
	metrics    *telemetry.Metrics
}

type deliveryKey struct {
	stream streamKey
	nonce  string
}

type streamKey struct {
	protocol string
	id       int64
}

type delivery struct {
	identity group.Identity
	typeURL  string
	version  string
}

func NewCallbacks(manager *Manager, logger *slog.Logger, metrics *telemetry.Metrics) *Callbacks {
	callbacks := &Callbacks{
		streams: make(map[streamKey]group.Identity), deliveries: make(map[deliveryKey]delivery),
		manager: manager, logger: logger, metrics: metrics,
	}
	callbacks.CallbackFuncs = serverv3.CallbackFuncs{
		StreamOpenFunc:          callbacks.onStreamOpen,
		StreamClosedFunc:        callbacks.onStreamClosed,
		DeltaStreamOpenFunc:     callbacks.onDeltaStreamOpen,
		DeltaStreamClosedFunc:   callbacks.onDeltaStreamClosed,
		StreamRequestFunc:       callbacks.onStreamRequest,
		StreamResponseFunc:      callbacks.onStreamResponse,
		StreamDeltaRequestFunc:  callbacks.onDeltaRequest,
		StreamDeltaResponseFunc: callbacks.onDeltaResponse,
		FetchRequestFunc: func(context.Context, *discoveryv3.DiscoveryRequest) error {
			return fmt.Errorf("REST xDS fetch is disabled; use ADS streaming")
		},
	}
	return callbacks
}

func (c *Callbacks) onStreamOpen(context.Context, int64, string) error {
	c.metrics.XDSStreams.WithLabelValues("sotw").Inc()
	return nil
}

func (c *Callbacks) onDeltaStreamOpen(context.Context, int64, string) error {
	c.metrics.XDSStreams.WithLabelValues("delta").Inc()
	return nil
}

func (c *Callbacks) onStreamClosed(streamID int64, node *corev3.Node) {
	c.metrics.XDSStreams.WithLabelValues("sotw").Dec()
	c.closeStream(streamKey{protocol: "sotw", id: streamID}, node)
}

func (c *Callbacks) onDeltaStreamClosed(streamID int64, node *corev3.Node) {
	c.metrics.XDSStreams.WithLabelValues("delta").Dec()
	c.closeStream(streamKey{protocol: "delta", id: streamID}, node)
}

func (c *Callbacks) onStreamRequest(streamID int64, request *discoveryv3.DiscoveryRequest) error {
	stream := streamKey{protocol: "sotw", id: streamID}
	identity, err := c.bind(stream, request.GetNode())
	if err != nil {
		return err
	}
	c.metrics.XDSRequests.WithLabelValues("sotw", shortType(request.GetTypeUrl())).Inc()
	if request.GetResponseNonce() != "" {
		c.resolveDelivery(stream, request.GetResponseNonce(), request.GetErrorDetail() != nil, sanitizeReason(request.GetErrorDetail().GetMessage()), identity)
	}
	return nil
}

func (c *Callbacks) onDeltaRequest(streamID int64, request *discoveryv3.DeltaDiscoveryRequest) error {
	stream := streamKey{protocol: "delta", id: streamID}
	identity, err := c.bind(stream, request.GetNode())
	if err != nil {
		return err
	}
	c.metrics.XDSRequests.WithLabelValues("delta", shortType(request.GetTypeUrl())).Inc()
	if request.GetResponseNonce() != "" {
		c.resolveDelivery(stream, request.GetResponseNonce(), request.GetErrorDetail() != nil, sanitizeReason(request.GetErrorDetail().GetMessage()), identity)
	}
	return nil
}

func (c *Callbacks) onStreamResponse(_ context.Context, streamID int64, request *discoveryv3.DiscoveryRequest, response *discoveryv3.DiscoveryResponse) {
	stream := streamKey{protocol: "sotw", id: streamID}
	identity, err := c.bind(stream, request.GetNode())
	if err != nil {
		c.logger.Error("cannot associate xDS response with node", "error", err)
		return
	}
	c.recordDelivery(stream, response.GetNonce(), delivery{identity: identity, typeURL: response.GetTypeUrl(), version: response.GetVersionInfo()})
	c.metrics.XDSResponses.WithLabelValues("sotw", shortType(response.GetTypeUrl())).Inc()
}

func (c *Callbacks) onDeltaResponse(streamID int64, request *discoveryv3.DeltaDiscoveryRequest, response *discoveryv3.DeltaDiscoveryResponse) {
	stream := streamKey{protocol: "delta", id: streamID}
	identity, err := c.bind(stream, request.GetNode())
	if err != nil {
		c.logger.Error("cannot associate delta xDS response with node", "error", err)
		return
	}
	c.recordDelivery(stream, response.GetNonce(), delivery{identity: identity, typeURL: response.GetTypeUrl(), version: response.GetSystemVersionInfo()})
	c.metrics.XDSResponses.WithLabelValues("delta", shortType(response.GetTypeUrl())).Inc()
}

func (c *Callbacks) bind(stream streamKey, node *corev3.Node) (group.Identity, error) {
	c.mu.Lock()
	if identity, ok := c.streams[stream]; ok {
		c.mu.Unlock()
		if node != nil && node.GetId() != "" && strings.ToLower(strings.TrimSpace(node.GetId())) != identity.NodeID {
			return group.Identity{}, fmt.Errorf("xDS stream changed node identity")
		}
		return identity, nil
	}
	c.mu.Unlock()
	identity, err := group.FromNode(node)
	if err != nil {
		return group.Identity{}, err
	}
	if err := c.manager.Connect(context.Background(), identity); err != nil {
		return group.Identity{}, err
	}
	c.mu.Lock()
	if existing, raced := c.streams[stream]; raced {
		c.mu.Unlock()
		c.manager.Disconnect(identity)
		return existing, nil
	}
	c.streams[stream] = identity
	c.mu.Unlock()
	c.logger.Info("Envoy xDS stream connected", "node", identity.NodeID, "group", identity.GroupKey)
	return identity, nil
}

func (c *Callbacks) closeStream(stream streamKey, node *corev3.Node) {
	c.mu.Lock()
	identity, ok := c.streams[stream]
	delete(c.streams, stream)
	for key := range c.deliveries {
		if key.stream == stream {
			delete(c.deliveries, key)
		}
	}
	c.mu.Unlock()
	if !ok && node != nil {
		identity, _ = group.FromNode(node)
		ok = identity.NodeID != ""
	}
	if ok {
		c.manager.Disconnect(identity)
		c.logger.Info("Envoy xDS stream disconnected", "node", identity.NodeID, "group", identity.GroupKey)
	}
}

func (c *Callbacks) recordDelivery(stream streamKey, nonce string, value delivery) {
	if nonce == "" || value.version == "" {
		return
	}
	c.mu.Lock()
	c.deliveries[deliveryKey{stream: stream, nonce: nonce}] = value
	c.mu.Unlock()
}

func (c *Callbacks) resolveDelivery(stream streamKey, nonce string, nack bool, reason string, fallback group.Identity) {
	key := deliveryKey{stream: stream, nonce: nonce}
	c.mu.Lock()
	value, ok := c.deliveries[key]
	delete(c.deliveries, key)
	c.mu.Unlock()
	if !ok {
		return
	}
	if value.identity.NodeID == "" {
		value.identity = fallback
	}
	if nack {
		ctx, cancel := rollbackContext()
		defer cancel()
		c.manager.NACK(ctx, value.identity, value.typeURL, value.version, nonce, reason)
		return
	}
	c.manager.ACK(value.identity, value.typeURL, value.version, nonce)
}

func sanitizeReason(value string) string {
	value = strings.Map(func(r rune) rune {
		if r == '\n' || r == '\r' || r == '\t' || r < 0x20 {
			return ' '
		}
		return r
	}, value)
	value = strings.Join(strings.Fields(value), " ")
	if len(value) > 256 {
		value = value[:256]
	}
	if value == "" {
		return "unspecified"
	}
	return value
}
