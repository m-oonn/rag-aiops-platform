FROM golang:1.25-alpine AS build
RUN apk add --no-cache git
WORKDIR /src
RUN git init && git remote add origin https://github.com/open-mcp-ai/Termcp.git && git fetch --depth 1 origin 0ee6536a41a7963e94afbbf1b4faa28eba1e2b86 && git checkout --detach FETCH_HEAD
COPY docker/termcp/approval-expiry.patch /tmp/approval-expiry.patch
RUN git apply --check /tmp/approval-expiry.patch && git apply /tmp/approval-expiry.patch
RUN go test ./internal/approval
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w -X main.version=0.2.7-aiops-expiry.1" -o /out/termcp .
FROM ghcr.io/open-mcp-ai/termcp:0.2.7@sha256:91c1f43685b27cf0d9e1aeef99f82b4efe3e802452bdd969a75a215a3b5d6bd1
COPY --from=build /out/termcp /usr/local/bin/termcp
LABEL org.opencontainers.image.source="https://github.com/open-mcp-ai/Termcp"
LABEL org.opencontainers.image.revision="0ee6536a41a7963e94afbbf1b4faa28eba1e2b86"
LABEL aiops.termcp.patch="approval-expiry.1"
