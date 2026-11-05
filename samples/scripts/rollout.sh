#!/usr/bin/env bash
# Roll the release forward, keep the previous revision for a quick undo.
set -euo pipefail

NS="${NS:-shop}"
RELEASE="shop-web"

helm upgrade "$RELEASE" ./helm/web --install \
    --namespace "$NS" --atomic --timeout 10m \
    -f values.yaml | tee "rollout-$(date +%F).log"

kubectl -n "$NS" rollout status deployment/api --timeout=300s
echo "done: $(helm -n "$NS" history "$RELEASE" --max 1 -o json | jq -r '.[0].revision')"
