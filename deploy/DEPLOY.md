# Deploying

The app is a single container: FastAPI serves both the JSON API and the static
frontend on one port. Any container host works. Two paths are documented here.

## AWS App Runner (recommended)

App Runner runs a container from ECR with HTTPS, autoscaling, and health checks —
no VPC or load balancer to manage. Cost is roughly $5–10/month for one small
instance at hobby traffic.

```bash
aws configure          # once: set access key, secret, region
./deploy/aws-apprunner.sh us-east-1
```

The script creates the ECR repo, builds and pushes the image, creates the
`AppRunnerECRAccessRole` IAM role if missing, and creates (or redeploys) the
service with `/healthz` health checks. It prints the public service URL.
`AutoDeploymentsEnabled` is on, so any later `docker push` to `:latest`
redeploys automatically.

To enable the AI chat assistant, add the secret after the first deploy:

```bash
aws apprunner update-service --service-arn <arn> \
  --source-configuration '{"ImageRepository": {"ImageIdentifier": "<ecr>:latest",
    "ImageRepositoryType": "ECR",
    "ImageConfiguration": {"Port": "8000",
      "RuntimeEnvironmentVariables": {"ANTHROPIC_API_KEY": "sk-ant-..."}}}}'
```

(For production, prefer referencing an AWS Secrets Manager secret via
`RuntimeEnvironmentSecrets` instead of a plain env var.)

## Azure Container Apps (alternative)

```bash
az login
az group create -n pdt-rg -l eastus
az acr create -n pdtregistry -g pdt-rg --sku Basic --admin-enabled true
az acr build -r pdtregistry -t portfolio-decision-tool:latest .
az containerapp env create -n pdt-env -g pdt-rg -l eastus
az containerapp create -n portfolio-decision-tool -g pdt-rg \
  --environment pdt-env \
  --image pdtregistry.azurecr.io/portfolio-decision-tool:latest \
  --registry-server pdtregistry.azurecr.io \
  --target-port 8000 --ingress external \
  --cpu 0.5 --memory 1Gi \
  --env-vars CACHE_MAX_AGE=3600
az containerapp show -n portfolio-decision-tool -g pdt-rg \
  --query properties.configuration.ingress.fqdn -o tsv
```

Add `ANTHROPIC_API_KEY` with `az containerapp secret set` +
`--env-vars ANTHROPIC_API_KEY=secretref:anthropic-key` to enable the chat
assistant.

## Environment variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs session cookies. **Set a long random value in production** (`openssl rand -hex 32`); without it sessions reset on every restart. |
| `COOKIE_SECURE` | Set to `1` behind HTTPS (App Runner / Container Apps) so session cookies are Secure-only. |
| `ANTHROPIC_API_KEY` | Enables Claude-generated chat answers (optional). |
| `CACHE_MAX_AGE` | Price cache TTL in seconds (default 3600). |
| `DB_PATH` | SQLite location (default `db/app.db`). |

**Accounts durability:** users/watchlists live in SQLite. On App Runner the
container filesystem is ephemeral — accounts reset on redeploy. Fine while the
feature is light; when accounts matter, point `DB_PATH` at a mounted volume
(Azure Container Apps + Azure Files works today) or migrate to RDS/Postgres.

## Notes

- The container starts with an empty price cache; the first request downloads
  ~10 ticker histories from Yahoo Finance (10–20 s), then everything is cached
  and refreshed hourly (`CACHE_MAX_AGE`, seconds).
- Without `ANTHROPIC_API_KEY` the chat assistant still works in extractive
  mode (returns the top knowledge-base passage verbatim).
- The container is stateless — no database. Scale-out is safe; each instance
  keeps its own price cache.
