# Runner control plane and Envoy egress split

The restricted sandbox has two independent socket planes:

- Runner control gRPC: `runner -> Unix socket -> orchestrator`.
- Sandbox egress: `runner local HTTP proxy -> Envoy http.sock -> upstream`.

Envoy must not proxy runner gRPC. It only owns the egress socket.

## Linux deployment

Use host bind mounts on a native Linux filesystem:

```env
JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR=/data/wgl/joysafeter/orchestrator/runner-control
JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH=/control/grpc.sock
JOYSAFETER_ENVOY_SOCKET_HOST_DIR=/data/wgl/joysafeter/envoy/envoy-sockets
JOYSAFETER_ENVOY_CONFIG_DIR=/data/wgl/joysafeter/envoy/envoy-config
JOYSAFETER_ENVOY_SOCKET_SUBPATH_MOUNT=false
```

The orchestrator creates:

```text
/data/wgl/joysafeter/orchestrator/runner-control/grpc.sock
```

The sandbox sees it as:

```text
/control/grpc.sock
```

The Envoy egress socket remains per sandbox:

```text
/sockets/<sandbox_id>/http.sock
```

## Local Docker Desktop development

Docker Desktop does not reliably support connecting to Unix sockets that are
created on a macOS host bind mount from inside Linux containers. Symptoms are:

```text
Operation not supported (os error 95)
```

Use a Docker volume for the runner control socket and a small local socat proxy:

```env
JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME=joysafeter-runner-control
JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH=/control/grpc.sock
```

The proxy listens on the Docker volume at `/control/grpc.sock` and forwards to
the host orchestrator TCP gRPC port. This is only for local Docker Desktop; Linux
servers should use the direct host-bind UDS config above.
