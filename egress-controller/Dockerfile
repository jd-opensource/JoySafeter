ARG GO_IMAGE=docker.m.daocloud.io/library/golang:1.26.5-bookworm@sha256:1ecb7edf62a0408027bd5729dfd6b1b8766e578e8df93995b225dfd0944eb651

FROM --platform=$BUILDPLATFORM ${GO_IMAGE} AS builder

ARG VERSION=dev
ARG GIT_COMMIT_SHA=unknown
ARG GOPROXY=https://goproxy.cn|https://proxy.golang.org|direct
ARG TARGETOS
ARG TARGETARCH
ENV GOPROXY=${GOPROXY}

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN target_os="${TARGETOS:-$(go env GOOS)}"; \
    target_arch="${TARGETARCH:-$(go env GOARCH)}"; \
    CGO_ENABLED=0 GOOS="${target_os}" GOARCH="${target_arch}" go build \
    -trimpath \
    -ldflags "-s -w -X main.version=${VERSION} -X main.commit=${GIT_COMMIT_SHA}" \
    -o /out/joysafeter-egress-controller ./cmd/controller

FROM scratch

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /out/joysafeter-egress-controller /usr/local/bin/joysafeter-egress-controller
COPY config/snapshots.example.json /etc/joysafeter-egress-controller/snapshots.json

USER 65532:65532
EXPOSE 18000 18080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD ["/usr/local/bin/joysafeter-egress-controller", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/joysafeter-egress-controller"]
