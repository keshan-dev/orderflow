#!/usr/bin/env bash
# Installs the cluster add-ons Phase 2 builds on: metrics-server, Envoy Gateway with the
# `orderflow` Gateway, cert-manager, and the namespaces. Safe to run again (helm upgrade --install).
#
# Usage (repo root, after create-cluster.sh):  bash deploy/kind/install-addons.sh
set -euo pipefail

METRICS_SERVER_CHART=3.14.0
ENVOY_GATEWAY_CHART=1.10.0
CERT_MANAGER_CHART=v1.21.3
HELM_TIMEOUT=5m

log() { echo "$(date -u +%H:%M:%S) $*"; }

kubectl config use-context kind-orderflow >/dev/null

log "namespaces"
kubectl apply -f deploy/kind/manifests/namespaces.yaml

log "metrics-server $METRICS_SERVER_CHART"
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/ >/dev/null
helm repo add jetstack https://charts.jetstack.io >/dev/null
helm repo update metrics-server jetstack >/dev/null
# kind kubelets use self-signed certificates, so metrics-server must not verify them.
helm upgrade --install metrics-server metrics-server/metrics-server \
  --version "$METRICS_SERVER_CHART" --namespace kube-system \
  --set 'args={--kubelet-insecure-tls}' --wait --timeout "$HELM_TIMEOUT"

log "envoy gateway $ENVOY_GATEWAY_CHART"
helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm \
  --version "$ENVOY_GATEWAY_CHART" --namespace envoy-gateway-system --create-namespace \
  --wait --timeout "$HELM_TIMEOUT"
kubectl apply -f deploy/kind/manifests/gateway.yaml

log "cert-manager $CERT_MANAGER_CHART"
helm upgrade --install cert-manager jetstack/cert-manager \
  --version "$CERT_MANAGER_CHART" --namespace cert-manager --create-namespace \
  --set crds.enabled=true --wait --timeout "$HELM_TIMEOUT"

log "waiting for the orderflow gateway"
kubectl wait --for=condition=Programmed gateway/orderflow -n envoy-gateway-system --timeout=180s

log "add-ons installed"
