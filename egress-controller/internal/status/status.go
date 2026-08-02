package status

import "github.com/joysafeter/joysafeter/egress-controller/internal/group"

type Recorder interface {
	// Published records a newly published generation. requiredTypes is the set
	// of xDS type URLs whose resources changed and therefore must be ACKed by
	// the connected nodes before the generation is 'applied'. When
	// appliedOnPublish is true the generation's content is identical to the
	// currently-serving one (no resource type changed): Envoy will send no delta
	// and thus no ACK, so it is recorded 'applied' immediately with the full
	// type list (required_type_urls must be non-empty per the schema).
	Published(groupKey string, generation uint64, version string, requiredTypes []string, appliedOnPublish bool)
	Connected(identity group.Identity)
	Disconnected(identity group.Identity)
	ACK(identity group.Identity, generation uint64, version, typeURL, nonce string)
	NACK(identity group.Identity, generation uint64, version, typeURL, nonce, reason string)
}

type NopRecorder struct{}

func (NopRecorder) Published(string, uint64, string, []string, bool)            {}
func (NopRecorder) Connected(group.Identity)                                    {}
func (NopRecorder) Disconnected(group.Identity)                                 {}
func (NopRecorder) ACK(group.Identity, uint64, string, string, string)          {}
func (NopRecorder) NACK(group.Identity, uint64, string, string, string, string) {}
