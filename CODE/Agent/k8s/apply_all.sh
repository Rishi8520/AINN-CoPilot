#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# Deploy AINN-CoPilot to Kubernetes
# Run from CODE/Agent/k8s/ directory
# Prerequisite: kubectl configured and cluster running (minikube or real)
# ─────────────────────────────────────────────────────────────────

set -e   # exit immediately on any error

echo "🚀 Deploying AINN-CoPilot to Kubernetes..."

echo "  [1/5] Creating namespace..."
kubectl apply -f namespace.yaml

echo "  [2/5] Applying ConfigMaps..."
kubectl apply -f configmap.yaml

echo "  [3/5] Applying Secrets..."
# In real deployment, generate secret.yaml from env vars first:
# kubectl create secret generic ainn-secrets \
#   --from-literal=HF_TOKEN=$HF_TOKEN \
#   --from-literal=LLM_ENDPOINT_URL=$LLM_ENDPOINT_URL \
#   -n ainn-copilot --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f secret.yaml

echo "  [4/5] Deploying agent..."
kubectl apply -f agent-deployment.yaml
kubectl apply -f agent-service.yaml

echo "  [5/5] Deploying UI..."
kubectl apply -f ui-deployment.yaml

echo ""
echo "✅ Deployment submitted. Checking pod status..."
kubectl get pods -n ainn-copilot

echo ""
echo "📡 UI will be accessible at: http://$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[0].address}'):30001"
echo ""
echo "Watch rollout: kubectl rollout status deployment/ainn-agent -n ainn-copilot"