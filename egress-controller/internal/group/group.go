package group

import (
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"strings"

	corev3 "github.com/envoyproxy/go-control-plane/envoy/config/core/v3"
	"google.golang.org/protobuf/types/known/structpb"
)

const SchemaVersion = "v1"

var requiredMetadata = []string{
	"deployment_id",
	"environment",
	"region",
	"provider",
	"shard_id",
	"envoy_version",
	"config_schema_version",
}

type Metadata struct {
	DeploymentID        string `json:"deployment_id"`
	Environment         string `json:"environment"`
	Region              string `json:"region"`
	Provider            string `json:"provider"`
	ShardID             string `json:"shard_id"`
	HostID              string `json:"host_id,omitempty"`
	EnvoyVersion        string `json:"envoy_version"`
	ConfigSchemaVersion string `json:"config_schema_version"`
}

type Identity struct {
	NodeID   string
	GroupKey string
	Metadata Metadata
}

type Hasher struct{}

func (Hasher) ID(node *corev3.Node) string {
	identity, err := FromNode(node)
	if err != nil {
		return "invalid-node"
	}
	return identity.GroupKey
}

func FromNode(node *corev3.Node) (Identity, error) {
	if node == nil {
		return Identity{}, errors.New("xDS node is required")
	}
	nodeID := normalize(node.GetId())
	if nodeID == "" {
		return Identity{}, errors.New("xDS node.id is required")
	}
	metadata, err := FromStruct(node.GetMetadata())
	if err != nil {
		return Identity{}, err
	}
	key, err := metadata.Key()
	if err != nil {
		return Identity{}, err
	}
	return Identity{NodeID: nodeID, GroupKey: key, Metadata: metadata}, nil
}

func FromStruct(value *structpb.Struct) (Metadata, error) {
	if value == nil {
		return Metadata{}, errors.New("xDS node.metadata is required")
	}
	fields := value.GetFields()
	for _, name := range requiredMetadata {
		field, ok := fields[name]
		if !ok || normalize(field.GetStringValue()) == "" {
			return Metadata{}, fmt.Errorf("xDS node metadata %q is required", name)
		}
	}
	metadata := Metadata{
		DeploymentID:        normalize(fields["deployment_id"].GetStringValue()),
		Environment:         normalize(fields["environment"].GetStringValue()),
		Region:              normalize(fields["region"].GetStringValue()),
		Provider:            normalize(fields["provider"].GetStringValue()),
		ShardID:             normalize(fields["shard_id"].GetStringValue()),
		EnvoyVersion:        normalize(fields["envoy_version"].GetStringValue()),
		ConfigSchemaVersion: normalize(fields["config_schema_version"].GetStringValue()),
	}
	if field, ok := fields["host_id"]; ok {
		metadata.HostID = normalize(field.GetStringValue())
	}
	if metadata.Provider == "docker" && metadata.HostID == "" {
		return Metadata{}, errors.New("xDS Docker node metadata \"host_id\" is required")
	}
	return metadata, nil
}

func (m Metadata) Key() (string, error) {
	values := []string{
		normalize(m.DeploymentID), normalize(m.Environment), normalize(m.Region),
		normalize(m.Provider), normalize(m.ShardID), normalize(m.HostID),
		normalize(m.EnvoyVersion), normalize(m.ConfigSchemaVersion),
	}
	if values[3] != "docker" {
		values[5] = ""
	}
	for index, value := range values {
		if index == 5 && values[3] != "docker" {
			continue
		}
		if value == "" {
			return "", errors.New("node-group metadata is incomplete")
		}
		if strings.ContainsAny(value, "\x00\n\r") {
			return "", errors.New("node-group metadata contains control characters")
		}
	}
	canonical := strings.Join(values, "\x00")
	digest := sha256.Sum256([]byte(canonical))
	return SchemaVersion + ":" + base64.RawURLEncoding.EncodeToString(digest[:]), nil
}

func normalize(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}
