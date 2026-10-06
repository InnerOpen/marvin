# Marvin Helm Deployment Guide

Complete step-by-step guide for deploying Marvin to OpenShift using Helm.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Pre-Deployment Checklist](#pre-deployment-checklist)
- [Initial Setup (One-Time)](#initial-setup-one-time)
- [Deployment Process](#deployment-process)
- [Post-Deployment Verification](#post-deployment-verification)
- [Monitoring](#monitoring)
- [Maintenance](#maintenance)

---

## Prerequisites

### Required Tools

- **Helm 3.0+**: [Installation guide](https://helm.sh/docs/intro/install/)
- **OpenShift CLI (oc)**: Configured and authenticated
- **Docker**: For building images (if not using CI/CD)
- **Git**: For version tagging

### Required Access

- OpenShift cluster access with project creation permissions
- Container registry access (push/pull)
- Project namespace admin rights

### Resource Requirements

**Development:**
- CPU: 100m request, 500m limit
- Memory: 256Mi request, 512Mi limit
- Storage: 10Gi

**Production:**
- CPU: 250m request, 1000m limit per pod
- Memory: 512Mi request, 1Gi limit per pod
- Storage: 50Gi
- Replicas: 2 (for high availability)

---

## Pre-Deployment Checklist

Before deploying to any environment, complete this checklist:

- [ ] Code changes reviewed and approved
- [ ] Tests passing in CI/CD pipeline
- [ ] Migration tested on dev/staging environment
- [ ] Database backup procedure tested (test restore)
- [ ] Maintenance window scheduled (production only)
- [ ] Users notified of maintenance (production only)
- [ ] Container image built and pushed to registry
- [ ] Secrets prepared (sealed-secrets or vault)
- [ ] Helm chart linted: `helm lint ./marvin-chart`
- [ ] Rollback procedure reviewed
- [ ] Monitoring/alerting configured

---

## Initial Setup (One-Time)

### 1. Install Helm 3

```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Windows
choco install kubernetes-helm

# Verify installation
helm version
```

### 2. Login to OpenShift

```bash
# Login to your cluster
oc login <cluster-url> --token=<your-token>

# Or with username/password
oc login <cluster-url> -u <username> -p <password>

# Verify login
oc whoami
oc cluster-info
```

### 3. Create Project Namespace

```bash
# Development
oc new-project marvin-dev

# Staging
oc new-project marvin-staging

# Production
oc new-project marvin-prod

# Verify project
oc project
```

### 4. Setup Container Registry

#### Option A: OpenShift Internal Registry

```bash
# Enable internal registry (if not enabled)
oc get route -n openshift-image-registry

# Login to internal registry
docker login -u $(oc whoami) -p $(oc whoami -t) $(oc registry info)

# Tag and push image
docker build -f docker/Dockerfile --target production --tag marvin:latest .
docker tag marvin:latest $(oc registry info)/marvin-prod/marvin:$(git rev-parse --short HEAD)
docker push $(oc registry info)/marvin-prod/marvin:$(git rev-parse --short HEAD)
```

#### Option B: External Registry (Quay.io, Docker Hub)

```bash
# Login to external registry
docker login quay.io -u <username>

# Build and push
docker build -f docker/Dockerfile --target production --tag marvin:latest .
docker tag marvin:latest quay.io/<username>/marvin:$(git rev-parse --short HEAD)
docker push quay.io/<username>/marvin:$(git rev-parse --short HEAD)

# Create pull secret in OpenShift
oc create secret docker-registry marvin-registry \
  --docker-server=quay.io \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email>

# Link secret to service account
oc secrets link default marvin-registry --for=pull
```

### 5. Configure Secrets (Production)

For production, use sealed-secrets or external secret management:

```bash
# Install sealed-secrets controller (if not already installed)
# https://github.com/bitnami-labs/sealed-secrets

# Create secret
kubectl create secret generic marvin-secrets \
  --namespace marvin-prod \
  --from-literal=SMTP_HOST=smtp.example.com \
  --from-literal=SMTP_PORT=587 \
  --from-literal=SMTP_USER=youruser \
  --from-literal=SMTP_PASSWORD=yourpassword \
  --from-literal=SMTP_FROM_EMAIL=noreply@yourdomain.com \
  --dry-run=client -o yaml | \
  kubeseal -o yaml > marvin-chart/templates/sealed-secret.yaml

# Disable default secret in values-production.yaml
# Comment out or remove the secret.yaml template
```

---

## Deployment Process

### Development Deployment

Quick deployment for testing:

```bash
# Switch to dev project
oc project marvin-dev

# Build and push image
docker build -f docker/Dockerfile --target production --tag marvin:dev-latest .
docker tag marvin:dev-latest <registry>/marvin:dev-latest
docker push <registry>/marvin:dev-latest

# Deploy with Helm
helm upgrade --install marvin ./marvin-chart \
  --namespace marvin-dev \
  --values marvin-chart/values.yaml \
  --set image.repository=<registry>/marvin \
  --set image.tag=dev-latest \
  --wait \
  --timeout 10m

# Watch deployment
oc get pods -w
```

### Staging Deployment

Staging deployment with git SHA tagging:

```bash
# Switch to staging project
oc project marvin-staging

# Get git commit SHA
GIT_SHA=$(git rev-parse --short HEAD)
echo "Deploying git SHA: $GIT_SHA"

# Build and push image
docker build -f docker/Dockerfile --target production \
  --build-arg COMMIT=$(git rev-parse HEAD) \
  --tag marvin:$GIT_SHA .
docker tag marvin:$GIT_SHA <registry>/marvin:$GIT_SHA
docker push <registry>/marvin:$GIT_SHA

# Dry-run first (preview changes)
helm upgrade marvin ./marvin-chart \
  --namespace marvin-staging \
  --values marvin-chart/values-staging.yaml \
  --set image.repository=<registry>/marvin \
  --set image.tag=$GIT_SHA \
  --dry-run --debug

# Deploy to staging
helm upgrade --install marvin ./marvin-chart \
  --namespace marvin-staging \
  --values marvin-chart/values-staging.yaml \
  --set image.repository=<registry>/marvin \
  --set image.tag=$GIT_SHA \
  --wait \
  --timeout 15m

# Verify deployment
helm status marvin -n marvin-staging
oc get pods
```

### Production Deployment

Production deployment with full safety checks:

#### Step 1: Pre-Deployment

```bash
# Switch to production project
oc project marvin-prod

# Verify current state
helm list -n marvin-prod
helm history marvin -n marvin-prod

# Get current pod
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
echo "Current pod: $POD"

# Backup database
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
echo "Creating backup: marvin-backup-$TIMESTAMP.tar.gz"
oc exec $POD -- tar czf /tmp/backup-$TIMESTAMP.tar.gz /app/data
oc cp $POD:/tmp/backup-$TIMESTAMP.tar.gz ./marvin-backup-$TIMESTAMP.tar.gz
oc exec $POD -- rm /tmp/backup-$TIMESTAMP.tar.gz

# Verify backup
ls -lh marvin-backup-$TIMESTAMP.tar.gz
tar tzf marvin-backup-$TIMESTAMP.tar.gz | head -10

# Document current migration version
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'
```

#### Step 2: Build and Push Image

```bash
# Get git commit SHA
GIT_SHA=$(git rev-parse --short HEAD)
echo "Deploying git SHA: $GIT_SHA"

# Tag stable version (for rollback)
docker tag marvin:latest marvin:stable

# Build new image
docker build -f docker/Dockerfile --target production \
  --build-arg COMMIT=$(git rev-parse HEAD) \
  --tag marvin:$GIT_SHA \
  --tag marvin:latest .

# Push to registry
docker tag marvin:$GIT_SHA <registry>/marvin:$GIT_SHA
docker tag marvin:latest <registry>/marvin:latest
docker push <registry>/marvin:$GIT_SHA
docker push <registry>/marvin:latest

# Keep stable tag
docker tag marvin:stable <registry>/marvin:stable
docker push <registry>/marvin:stable
```

#### Step 3: Dry-Run Deployment

```bash
# Preview changes
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml \
  --set image.repository=<registry>/marvin \
  --set image.tag=$GIT_SHA \
  --dry-run --debug > /tmp/helm-preview.yaml

# Review rendered templates
less /tmp/helm-preview.yaml

# Verify migration job will run
grep -A 20 "kind: Job" /tmp/helm-preview.yaml
```

#### Step 4: Execute Deployment

```bash
# Deploy with Helm (includes automatic migration via hook)
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml \
  --set image.repository=<registry>/marvin \
  --set image.tag=$GIT_SHA \
  --wait \
  --timeout 15m \
  --atomic  # Auto-rollback if deployment fails

# The --atomic flag ensures:
# - Helm waits for all resources to be ready
# - If anything fails, automatic rollback to previous release
# - Clean success or clean failure, no partial state
```

#### Step 5: Monitor Deployment

In a separate terminal, watch the deployment:

```bash
# Watch migration job
watch -n 2 'oc get jobs -l job-type=migration'

# Stream migration logs
MIGRATION_JOB=$(oc get jobs -l job-type=migration --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
oc logs -f job/$MIGRATION_JOB

# Watch pods
watch -n 2 'oc get pods'

# Watch deployment rollout
oc rollout status deployment/marvin --watch
```

#### Step 6: Immediate Verification

```bash
# Get new pod
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')

# Check pod logs (last 50 lines)
oc logs $POD --tail=50

# Verify migration status
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'

# Check state file
oc exec $POD -- cat /app/data/scheduler_state.json

# Verify health endpoint
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
curl -v https://$ROUTE/api/health

# Check Helm release
helm status marvin -n marvin-prod
helm history marvin -n marvin-prod
```

---

## Post-Deployment Verification

Complete this verification checklist after every deployment:

### Automated Checks

Run these commands to verify the deployment:

```bash
#!/bin/bash
# save as: verify-deployment.sh

set -e

echo "========================================="
echo "Marvin Deployment Verification"
echo "========================================="

# Get pod
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
echo "Pod: $POD"
echo ""

# 1. Pod status
echo "1. Pod Status:"
oc get pods -l app.kubernetes.io/name=marvin
echo ""

# 2. Migration status
echo "2. Migration Status:"
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'
echo ""

# 3. State file
echo "3. Scheduler State File:"
oc exec $POD -- cat /app/data/scheduler_state.json
echo ""

# 4. Health endpoint
echo "4. Health Endpoint:"
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
curl -s https://$ROUTE/api/health | jq .
echo ""

# 5. No tokens in logs
echo "5. Token Security Check (should be empty):"
oc logs $POD | grep -i "token.*:" | head -5 || echo "✓ No tokens found in logs"
echo ""

# 6. Execution logs table
echo "6. Webhook Execution Logs Table:"
oc exec $POD -- bash -c 'cd /app && uv run python -c "
from marvin.db.db_setup import session_context
from marvin.db.models.groups import WebhookExecutionLogModel
with session_context() as session:
    count = session.query(WebhookExecutionLogModel).count()
    print(f\"Execution logs count: {count}\")
"'
echo ""

# 7. Helm release
echo "7. Helm Release:"
helm status marvin -n marvin-prod
echo ""

echo "========================================="
echo "Verification Complete"
echo "========================================="
```

Make executable and run:

```bash
chmod +x verify-deployment.sh
./verify-deployment.sh
```

### Manual Tests

After automated checks pass, perform manual testing:

1. **Create Test Webhook**
   ```bash
   # Use admin UI or API to create a test webhook
   # with a future datetime (not just time)
   ```

2. **Trigger Token Refresh**
   ```bash
   # Login to application
   # Refresh access token
   # Verify no JWT in logs:
   oc logs $POD --tail=100 | grep -i "token"
   ```

3. **Simulate Failed Webhook**
   ```bash
   # Create webhook pointing to non-existent endpoint
   # Wait for scheduler to process
   # Check retry behavior and execution logs
   ```

4. **Restart Pod**
   ```bash
   # Delete pod to trigger restart
   oc delete pod $POD

   # Wait for new pod
   oc wait --for=condition=ready pod -l app.kubernetes.io/name=marvin --timeout=120s

   # Verify scheduler_state.json loads correctly
   NEW_POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
   oc logs $NEW_POD | grep -i "scheduler_state"
   ```

5. **Monitor for 24 Hours**
   - Watch for pod restarts
   - Monitor memory usage trends
   - Check for unexpected errors
   - Verify webhook delivery success rate

---

## Monitoring

### Key Metrics to Watch

```bash
# Pod resource usage
oc adm top pods

# Pod restart count
oc get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.containerStatuses[0].restartCount}{"\n"}{end}'

# PVC usage
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc exec $POD -- df -h /app/data

# Database file size
oc exec $POD -- ls -lh /app/data/*.db
```

### Log Monitoring

```bash
# Stream logs
oc logs -f deployment/marvin

# Check for errors
oc logs deployment/marvin --tail=1000 | grep ERROR

# Check webhook failures
oc logs deployment/marvin --tail=1000 | grep "webhook.*failed"

# Check scheduler activity
oc logs deployment/marvin --tail=1000 | grep "scheduler"
```

### Alerts to Configure

Set up alerts for:
- Pod restart count > 0
- Memory usage > 80%
- Disk usage > 80%
- HTTP 5xx error rate increase
- Webhook failure rate > 10%
- Database size growth anomaly

---

## Maintenance

### Viewing Release History

```bash
# List all releases
helm list -n marvin-prod

# View release history
helm history marvin -n marvin-prod

# Get release details
helm get all marvin -n marvin-prod

# View values for specific revision
helm get values marvin --revision 3 -n marvin-prod
```

### Updating Configuration Only

To update configuration without changing the image:

```bash
# Edit values-production.yaml
vim marvin-chart/values-production.yaml

# Apply changes
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml \
  --reuse-values  # Keep existing values, only update changed ones
```

### Scaling

```bash
# Scale via Helm values
# Edit replicaCount in values-production.yaml
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml

# Or scale directly (temporary)
oc scale deployment/marvin --replicas=3

# Verify
oc get pods -l app.kubernetes.io/name=marvin
```

### Upgrading Helm Chart

When updating the chart itself:

```bash
# Bump chart version in Chart.yaml
vim marvin-chart/Chart.yaml

# Lint changes
helm lint ./marvin-chart

# Test rendering
helm template marvin ./marvin-chart \
  --values marvin-chart/values-production.yaml

# Deploy updated chart
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml
```

### Database Backup Automation

Create a CronJob for automated backups:

```yaml
# save as: backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: marvin-backup
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: marvin:latest
            command:
              - /bin/bash
              - -c
              - |
                tar czf /tmp/backup-$(date +%Y%m%d).tar.gz /app/data
                # Upload to S3 or backup location
          volumeMounts:
          - name: data
            mountPath: /app/data
          volumes:
          - name: data
            persistentVolumeClaim:
              claimName: marvin-data
          restartPolicy: OnFailure
```

Apply:

```bash
oc apply -f backup-cronjob.yaml
```

---

## Troubleshooting

See `ROLLBACK_PROCEDURES.md` for detailed troubleshooting and rollback procedures.

### Quick Fixes

**Pod won't start:**
```bash
oc describe pod $POD
oc logs $POD --previous
```

**Migration failed:**
```bash
MIGRATION_JOB=$(oc get jobs -l job-type=migration --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
oc logs job/$MIGRATION_JOB
oc delete job $MIGRATION_JOB  # Then retry deployment
```

**PVC issues:**
```bash
oc get pvc
oc describe pvc marvin-data
```

**Helm release stuck:**
```bash
helm list -n marvin-prod --all
helm uninstall marvin -n marvin-prod  # Nuclear option
```

---

## Additional Resources

- **Helm Documentation**: https://helm.sh/docs/
- **OpenShift Documentation**: https://docs.openshift.com/
- **Chart README**: See `marvin-chart/README.md`
- **Rollback Guide**: See `ROLLBACK_PROCEDURES.md`
- **Implementation Details**: See `IMPLEMENTATION_SUMMARY.md`

---

## Support

For issues:
1. Check pod logs: `oc logs $POD`
2. Check Helm release: `helm status marvin`
3. Check events: `oc get events --sort-by='.lastTimestamp'`
4. Review migration logs: `oc logs job/$MIGRATION_JOB`
5. Consult ROLLBACK_PROCEDURES.md if rollback needed
