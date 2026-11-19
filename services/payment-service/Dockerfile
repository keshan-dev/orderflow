# Build from the repository root:
#   docker build -f services/payment-service/Dockerfile .

# Stage 1: build a static binary (no C library needed).
FROM golang:1.27.4-alpine AS build
WORKDIR /src
COPY services/payment-service/go.mod services/payment-service/go.sum ./
RUN go mod download
COPY services/payment-service/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /payment-service ./cmd/payment-service

# Stage 2: distroless has no shell or package manager, and runs as a non-root user.
FROM gcr.io/distroless/static-debian12:nonroot@sha256:afa5c872c891853ca7fcf1f12c3edb23f7eeef36189728842dd51042ff57f7ab
COPY --from=build /payment-service /payment-service
EXPOSE 8003
USER nonroot
ENTRYPOINT ["/payment-service"]
