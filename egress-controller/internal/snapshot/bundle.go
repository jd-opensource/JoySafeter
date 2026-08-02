package snapshot

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"sort"
	"strconv"
	"strings"

	clusterv3 "github.com/envoyproxy/go-control-plane/envoy/config/cluster/v3"
	listenerv3 "github.com/envoyproxy/go-control-plane/envoy/config/listener/v3"
	routev3 "github.com/envoyproxy/go-control-plane/envoy/config/route/v3"
	cachetypes "github.com/envoyproxy/go-control-plane/pkg/cache/types"
	cachev3 "github.com/envoyproxy/go-control-plane/pkg/cache/v3"
	resourcev3 "github.com/envoyproxy/go-control-plane/pkg/resource/v3"
	"github.com/joysafeter/joysafeter/egress-controller/internal/group"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const BundleSchemaVersion = 1

type Bundle struct {
	SchemaVersion int           `json:"schema_version"`
	Groups        []GroupBundle `json:"groups"`
}

type GroupBundle struct {
	Metadata   group.Metadata `json:"metadata"`
	Generation uint64         `json:"generation"`
	Resources  Resources      `json:"resources"`
}

type Resources struct {
	Clusters  []json.RawMessage `json:"clusters"`
	Routes    []json.RawMessage `json:"routes"`
	Listeners []json.RawMessage `json:"listeners"`
}

type Compiled struct {
	GroupKey      string
	Generation    uint64
	Version       string
	RequiredTypes []string
	Snapshot      *cachev3.Snapshot
}

func ReadFile(path string, maxBytes int64) (Bundle, error) {
	file, err := os.Open(path)
	if err != nil {
		return Bundle{}, fmt.Errorf("open snapshot bundle: %w", err)
	}
	defer file.Close()

	data, err := io.ReadAll(io.LimitReader(file, maxBytes+1))
	if err != nil {
		return Bundle{}, fmt.Errorf("read snapshot bundle: %w", err)
	}
	if int64(len(data)) > maxBytes {
		return Bundle{}, fmt.Errorf("snapshot bundle exceeds %d bytes", maxBytes)
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var bundle Bundle
	if err := decoder.Decode(&bundle); err != nil {
		return Bundle{}, fmt.Errorf("decode snapshot bundle: %w", err)
	}
	if err := ensureEOF(decoder); err != nil {
		return Bundle{}, err
	}
	return bundle, nil
}

func Compile(bundle Bundle) ([]Compiled, error) {
	if bundle.SchemaVersion != BundleSchemaVersion {
		return nil, fmt.Errorf("unsupported snapshot schema version %d", bundle.SchemaVersion)
	}
	compiled := make([]Compiled, 0, len(bundle.Groups))
	seenGroups := make(map[string]struct{}, len(bundle.Groups))
	for index, item := range bundle.Groups {
		entry, err := compileGroup(item)
		if err != nil {
			return nil, fmt.Errorf("compile group %d: %w", index, err)
		}
		if _, exists := seenGroups[entry.GroupKey]; exists {
			return nil, fmt.Errorf("duplicate node group %q", entry.GroupKey)
		}
		seenGroups[entry.GroupKey] = struct{}{}
		compiled = append(compiled, entry)
	}
	sort.Slice(compiled, func(i, j int) bool { return compiled[i].GroupKey < compiled[j].GroupKey })
	return compiled, nil
}

func compileGroup(item GroupBundle) (Compiled, error) {
	if item.Generation == 0 {
		return Compiled{}, errors.New("generation must be greater than zero")
	}
	groupKey, err := item.Metadata.Key()
	if err != nil {
		return Compiled{}, fmt.Errorf("metadata: %w", err)
	}
	clusters, err := decodeResources(item.Resources.Clusters, func() proto.Message { return &clusterv3.Cluster{} })
	if err != nil {
		return Compiled{}, fmt.Errorf("clusters: %w", err)
	}
	routes, err := decodeResources(item.Resources.Routes, func() proto.Message { return &routev3.RouteConfiguration{} })
	if err != nil {
		return Compiled{}, fmt.Errorf("routes: %w", err)
	}
	listeners, err := decodeResources(item.Resources.Listeners, func() proto.Message { return &listenerv3.Listener{} })
	if err != nil {
		return Compiled{}, fmt.Errorf("listeners: %w", err)
	}

	return BuildCompiled(groupKey, item.Generation, clusters, routes, listeners)
}

func BuildCompiled(
	groupKey string,
	generation uint64,
	clusters, routes, listeners []cachetypes.Resource,
) (Compiled, error) {
	if strings.TrimSpace(groupKey) == "" {
		return Compiled{}, errors.New("group key is required")
	}
	if generation == 0 {
		return Compiled{}, errors.New("generation must be greater than zero")
	}
	version, err := deterministicVersion(generation, clusters, routes, listeners)
	if err != nil {
		return Compiled{}, err
	}
	xdsSnapshot, err := cachev3.NewSnapshot(version, map[resourcev3.Type][]cachetypes.Resource{
		resourcev3.ClusterType:  clusters,
		resourcev3.RouteType:    routes,
		resourcev3.ListenerType: listeners,
	})
	if err != nil {
		return Compiled{}, fmt.Errorf("create snapshot: %w", err)
	}
	if err := xdsSnapshot.Consistent(); err != nil {
		return Compiled{}, fmt.Errorf("inconsistent snapshot: %w", err)
	}
	if err := xdsSnapshot.ConstructVersionMap(); err != nil {
		return Compiled{}, fmt.Errorf("construct delta version map: %w", err)
	}
	requiredTypes := []string{resourcev3.ClusterType, resourcev3.ListenerType}
	if len(routes) > 0 {
		requiredTypes = append(requiredTypes, resourcev3.RouteType)
	}
	return Compiled{
		GroupKey: groupKey, Generation: generation, Version: version,
		RequiredTypes: requiredTypes, Snapshot: xdsSnapshot,
	}, nil
}

func decodeResources(raw []json.RawMessage, newMessage func() proto.Message) ([]cachetypes.Resource, error) {
	resources := make([]cachetypes.Resource, 0, len(raw))
	seenNames := make(map[string]struct{}, len(raw))
	unmarshal := protojson.UnmarshalOptions{DiscardUnknown: false}
	for index, document := range raw {
		message := newMessage()
		if err := unmarshal.Unmarshal(document, message); err != nil {
			return nil, fmt.Errorf("resource %d: %w", index, err)
		}
		resource, ok := message.(cachetypes.Resource)
		if !ok {
			return nil, fmt.Errorf("resource %d has unsupported protobuf type", index)
		}
		name := strings.TrimSpace(cachev3.GetResourceName(resource))
		if name == "" {
			return nil, fmt.Errorf("resource %d has empty name", index)
		}
		if _, exists := seenNames[name]; exists {
			return nil, fmt.Errorf("duplicate resource name %q", name)
		}
		seenNames[name] = struct{}{}
		resources = append(resources, resource)
	}
	sort.Slice(resources, func(i, j int) bool {
		return cachev3.GetResourceName(resources[i]) < cachev3.GetResourceName(resources[j])
	})
	return resources, nil
}

func deterministicVersion(generation uint64, groups ...[]cachetypes.Resource) (string, error) {
	hash := sha256.New()
	hash.Write([]byte(strconv.FormatUint(generation, 10)))
	marshal := proto.MarshalOptions{Deterministic: true}
	for _, resources := range groups {
		for _, resource := range resources {
			hash.Write([]byte{0})
			hash.Write([]byte(cachev3.GetResourceName(resource)))
			encoded, err := marshal.Marshal(resource)
			if err != nil {
				return "", fmt.Errorf("marshal resource %q: %w", cachev3.GetResourceName(resource), err)
			}
			hash.Write(encoded)
		}
	}
	return fmt.Sprintf("g%d-%s", generation, hex.EncodeToString(hash.Sum(nil)[:16])), nil
}

func ensureEOF(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); err == io.EOF {
		return nil
	} else if err != nil {
		return fmt.Errorf("decode trailing snapshot data: %w", err)
	}
	return errors.New("snapshot bundle contains multiple JSON documents")
}
