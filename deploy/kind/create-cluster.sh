#!/usr/bin/env bash
# Creates the kind cluster and a local image registry at 127.0.0.1:5001, following the kind
# "Local Registry" guide. Safe to run again: existing pieces are kept.
#
# Usage (repo root, Git Bash):  bash deploy/kind/create-cluster.sh
set -euo pipefail

CLUSTER=orderflow
REGISTRY_NAME=kind-registry
REGISTRY_PORT=5001
REGISTRY_IMAGE=registry:3.0.0

log() { echo "$(date -u +%H:%M:%S) $*"; }

if [ "$(docker inspect -f '{{.State.Running}}' "$REGISTRY_NAME" 2>/dev/null || true)" != "true" ]; then
  log "starting registry $REGISTRY_NAME on 127.0.0.1:$REGISTRY_PORT"
  docker run -d --restart=always -p "127.0.0.1:$REGISTRY_PORT:5000" --network bridge \
    --name "$REGISTRY_NAME" "$REGISTRY_IMAGE" >/dev/null
fi

if kind get clusters | grep -qx "$CLUSTER"; then
  log "cluster $CLUSTER already exists"
else
  log "creating cluster $CLUSTER"
  kind create cluster --config deploy/kind/kind-config.yaml
fi

# Inside the nodes, localhost:5001 must point at the registry container, not the node itself.
for node in $(kind get nodes --name "$CLUSTER"); do
  MSYS_NO_PATHCONV=1 docker exec "$node" mkdir -p "/etc/containerd/certs.d/localhost:$REGISTRY_PORT"
  printf '[host."http://%s:5000"]\n' "$REGISTRY_NAME" \
    | MSYS_NO_PATHCONV=1 docker exec -i "$node" cp /dev/stdin "/etc/containerd/certs.d/localhost:$REGISTRY_PORT/hosts.toml"
done

if [ "$(docker inspect -f '{{json .NetworkSettings.Networks.kind}}' "$REGISTRY_NAME")" = "null" ]; then
  docker network connect kind "$REGISTRY_NAME"
fi

# Tells tools in the cluster where the local registry is (KEP-1755).
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:$REGISTRY_PORT"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF

log "cluster $CLUSTER is ready; push images to localhost:$REGISTRY_PORT/<name>:<tag>"
