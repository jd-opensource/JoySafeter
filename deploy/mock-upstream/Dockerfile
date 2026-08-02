# Mock upstream echo server for the Docker egress smoke (Plan 2 / C-2).
# Reuses the same pinned Go base as the egress-controller so CI never pulls a
# third-party echo image. No modules, so no `go mod download` step is needed.
ARG GO_IMAGE=docker.m.daocloud.io/library/golang:1.26.5-bookworm@sha256:1ecb7edf62a0408027bd5729dfd6b1b8766e578e8df93995b225dfd0944eb651

FROM ${GO_IMAGE} AS builder
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags "-s -w" -o /out/mock-upstream .

FROM scratch
COPY --from=builder /out/mock-upstream /usr/local/bin/mock-upstream
USER 65532:65532
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/mock-upstream"]
