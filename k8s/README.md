# ACIP Kubernetes Deployment

## Prerequisites

- A K8s cluster on Hetzner Cloud or DigitalOcean
- `kubectl` configured for the cluster
- `cert-manager` installed (for TLS)
- nginx ingress controller installed
- `KUBECONFIG` secret set in GitHub repository settings

## First-time setup

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Upload init scripts as a ConfigMap (runs on first Postgres start)
#    Files are applied alphabetically: 00-init.sql enables pgvector, 01-schema.sql creates tables
kubectl create configmap postgres-schema \
  --from-file=00-init.sql=k8s/postgres-init.sql \
  --from-file=01-schema.sql=schema.sql \
  -n acip --dry-run=client -o yaml | kubectl apply -f -

# 3. Fill in secrets.yaml with base64-encoded values, then apply
#    (or use your secrets manager of choice)
kubectl apply -f k8s/secrets.yaml -n acip

# 4. Apply everything else
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/worker-deployment.yaml
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/hpa-api.yaml

# 5. Verify
kubectl get pods -n acip
kubectl logs -l app=acip-api -n acip --tail=50
```

## Migrating from SQLite (existing home server installation)

```bash
# Run migration script against the remote Postgres
python scripts/migrate_sqlite_to_postgres.py \
  --sqlite /path/to/acip.db \
  --postgres postgresql://acip:PASSWORD@your-db-host/acip

# Then reembed all projects (embeddings are not migrated — format differs)
# Call reembed_project(<project_id>) for each project via the MCP interface
```

## Scaling workers

Workers scale automatically with KEDA if installed:
```bash
kubectl apply -f k8s/hpa-worker.yaml
```

Without KEDA, scale manually:
```bash
kubectl scale deployment acip-worker --replicas=3 -n acip
```

## Production Postgres (recommended)

Replace `k8s/postgres.yaml` with a managed database connection:
1. Create a Hetzner Managed DB or DO Managed Postgres instance
2. Update `DATABASE_URL` in `k8s/secrets.yaml`
3. Delete/skip `k8s/postgres.yaml`

## Useful commands

```bash
# Check pod status
kubectl get pods -n acip

# Tail API logs
kubectl logs -l app=acip-api -n acip -f

# Tail worker logs
kubectl logs -l app=acip-worker -n acip -f

# Check queue depth
kubectl exec -it deployment/redis -n acip -- redis-cli llen rq:queue:acip-indexing

# Force rollout (after pushing new image)
kubectl rollout restart deployment/acip-api deployment/acip-worker -n acip
```
