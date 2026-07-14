# =============================================================================
# Matterbridge Dockerfile
# =============================================================================
# Builds a minimal Matterbridge container for bridging chat platforms to MIVE.
#
# Build:  docker build -f docker/matterbridge.dockerfile -t mive-matterbridge .
# Run:    docker run -v ./config/matterbridge.toml:/etc/matterbridge/matterbridge.toml mive-matterbridge
# =============================================================================

FROM golang:1.22-alpine AS builder

ARG MATTERBRIDGE_VERSION=1.26.0

RUN apk add --no-cache git ca-certificates

RUN git clone --depth 1 --branch v${MATTERBRIDGE_VERSION} \
    https://github.com/42wim/matterbridge.git /src

WORKDIR /src

RUN CGO_ENABLED=0 go build -mod=vendor -ldflags="-s -w" -o /matterbridge .

# ---------------------------------------------------------------------------
FROM alpine:3.19

RUN apk add --no-cache ca-certificates tzdata

COPY --from=builder /matterbridge /usr/local/bin/matterbridge

# Default config location (mount your config here)
VOLUME ["/etc/matterbridge"]

# Expose the REST API port
EXPOSE 4242

# Healthcheck: hit the API health endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://localhost:4242/api/health || exit 1

ENTRYPOINT ["matterbridge"]
CMD ["-conf", "/etc/matterbridge/matterbridge.toml"]
