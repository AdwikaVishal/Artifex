#!/usr/bin/env bash
# deploy_k8s.sh – apply all Kubernetes manifests to the current cluster context
set -euo pipefail

NAMESPACE="artifex"
REGISTRY="${REGISTRY:-artifex}"
TAG="${TAG:-latest}"

echo "🚀 Deploying Artifex to Kubernetes (namespace: $NAMESPACE)..."

# 1. Namespace
kubectl apply -f k8s/namespace.yaml

# 2. ConfigMap
kubectl apply -f k8s/configmap.yaml

# 3. Secrets (must exist – not committed to git)
if [ -f k8s/secrets.yaml ]; then
  kubectl apply -f k8s/secrets.yaml
else
  echo "⚠️  k8s/secrets.yaml not found – create it with your OPENAI_API_KEY"
  exit 1
fi

# 4. Services
kubectl apply -f k8s/services/

# 5. Deployments
kubectl apply -f k8s/deployments/

echo ""
echo "✅ Manifests applied. Checking rollout status..."
for deploy in planner retriever executor validator supervisor api temporal-worker; do
  kubectl rollout status deployment/$deploy -n $NAMESPACE --timeout=120s
done

echo ""
echo "🎉 Artifex deployed successfully!"
echo "   API service: $(kubectl get svc artifex-api -n $NAMESPACE -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
