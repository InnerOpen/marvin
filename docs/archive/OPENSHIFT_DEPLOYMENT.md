# OpenShift Deployment Guide - Event Bus Security & Scheduler Reliability Fixes

**Date:** 2026-06-05
**Target:** OpenShift Container Platform
**Migration Required:** Yes (Breaking Changes)

## Overview

This deployment includes database schema changes that require a migration. The application must be stopped during the migration to prevent data corruption.

## Pre-Deployment Checklist

- [ ] Review all changes in `IMPLEMENTATION_SUMMARY.md`
- [ ] Schedule maintenance window (estimated 15-30 minutes)
- [ ] Notify users of scheduled downtime
- [ ] Backup current database
- [ ] Have rollback plan ready

## Deployment Strategy

### Option 1: Blue/Green Deployment (Recommended for Production)

**Pros:**
- Zero downtime for most operations
- Easy rollback
- Test new version before cutover

**Cons:**
- Requires double resources temporarily
- Migration still requires brief downtime

**Steps:**
1. Deploy new version (green) alongside existing (blue)
2. Stop blue deployment to run migration
3. Run migration
4. Start green deployment
5. Verify green is healthy
6. Route traffic to green
7. Scale down blue after verification period

### Option 2: Rolling Update (Simpler, Some Downtime)

**Pros:**
- Simpler process
- Uses fewer resources

**Cons:**
- Requires downtime during migration
- Slower rollback

**Steps:**
1. Scale down to 0 replicas
2. Run database migration
3. Deploy new image
4. Scale up to desired replicas
5. Verify health

## OpenShift Configuration Files

### 1. BuildConfig (for building from source)

```yaml
# openshift/buildconfig.yaml
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: marvin
  labels:
    app: marvin
spec:
  source:
    type: Git
    git:
      uri: 'https://github.com/your-org/marvin.git'
      ref: main
    contextDir: .
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: docker/Dockerfile
      buildArgs:
        - name: COMMIT
          value: '${SOURCE_REV}'
  output:
    to:
      kind: ImageStreamTag
      name: 'marvin:latest'
  triggers:
    - type: ConfigChange
    - type: ImageChange
```

### 2. ImageStream

```yaml
# openshift/imagestream.yaml
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: marvin
  labels:
    app: marvin
spec:
  lookupPolicy:
    local: true
  tags:
    - name: latest
      annotations:
        description: Latest Marvin application image
      from:
        kind: DockerImage
        name: 'marvin:latest'
    - name: stable
      annotations:
        description: Last known stable version
```

### 3. DeploymentConfig

```yaml
# openshift/deploymentconfig.yaml
apiVersion: apps.openshift.io/v1
kind: DeploymentConfig
metadata:
  name: marvin
  labels:
    app: marvin
spec:
  replicas: 2
  selector:
    app: marvin
    deploymentconfig: marvin
  strategy:
    type: Rolling
    rollingParams:
      updatePeriodSeconds: 1
      intervalSeconds: 1
      timeoutSeconds: 600
      maxUnavailable: 1
      maxSurge: 1
  template:
    metadata:
      labels:
        app: marvin
        deploymentconfig: marvin
    spec:
      containers:
        - name: marvin
          image: 'marvin:latest'
          ports:
            - containerPort: 8080
              protocol: TCP
          env:
            - name: PRODUCTION
              value: "true"
            - name: ALLOW_SIGNUP
              value: "false"
            - name: LOG_LEVEL
              value: "INFO"
            - name: DB_ENGINE
              value: "sqlite"
            - name: DATA_DIR
              value: "/app/data"
            - name: API_PORT
              value: "8080"
            - name: HOST
              value: "0.0.0.0"
          envFrom:
            - secretRef:
                name: marvin-secrets
            - configMapRef:
                name: marvin-config
          volumeMounts:
            - name: marvin-data
              mountPath: /app/data
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /api/health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /api/health
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
      volumes:
        - name: marvin-data
          persistentVolumeClaim:
            claimName: marvin-data
  triggers:
    - type: ConfigChange
    - type: ImageChange
      imageChangeParams:
        automatic: true
        containerNames:
          - marvin
        from:
          kind: ImageStreamTag
          name: 'marvin:latest'
```

### 4. PersistentVolumeClaim (for database and state file)

```yaml
# openshift/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: marvin-data
  labels:
    app: marvin
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: gp2  # Adjust based on your cluster
```

### 5. Service

```yaml
# openshift/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: marvin
  labels:
    app: marvin
spec:
  selector:
    app: marvin
    deploymentconfig: marvin
  ports:
    - name: http
      protocol: TCP
      port: 8080
      targetPort: 8080
  type: ClusterIP
```

### 6. Route

```yaml
# openshift/route.yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: marvin
  labels:
    app: marvin
spec:
  to:
    kind: Service
    name: marvin
    weight: 100
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
  wildcardPolicy: None
```

### 7. ConfigMap

```yaml
# openshift/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: marvin-config
  labels:
    app: marvin
data:
  # Non-sensitive configuration
  LOG_LEVEL: "INFO"
  API_DOCS: "false"  # Disable in production
  LANG: "en-US"
  # Add other non-sensitive configs
```

### 8. Secret (create manually or via sealed-secrets)

```yaml
# openshift/secret.yaml (DO NOT COMMIT - use sealed-secrets or vault)
apiVersion: v1
kind: Secret
metadata:
  name: marvin-secrets
  labels:
    app: marvin
type: Opaque
stringData:
  # Add sensitive data here
  SMTP_HOST: "smtp.example.com"
  SMTP_PORT: "587"
  SMTP_FROM_EMAIL: "marvin@example.com"
  SMTP_AUTH_STRATEGY: "TLS"
  # Add database credentials if using postgres
```

### 9. Migration Job

```yaml
# openshift/migration-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: marvin-migration-$(date +%Y%m%d-%H%M%S)
  labels:
    app: marvin
    job-type: migration
spec:
  template:
    metadata:
      labels:
        app: marvin
        job-type: migration
    spec:
      restartPolicy: OnFailure
      containers:
        - name: migration
          image: 'marvin:latest'
          command:
            - /bin/bash
            - -c
            - |
              set -e
              echo "Starting database migration..."
              cd /app/src/marvin
              uv run alembic upgrade head
              echo "Migration complete!"
          env:
            - name: PRODUCTION
              value: "true"
            - name: DB_ENGINE
              value: "sqlite"
            - name: DATA_DIR
              value: "/app/data"
          envFrom:
            - secretRef:
                name: marvin-secrets
            - configMapRef:
                name: marvin-config
          volumeMounts:
            - name: marvin-data
              mountPath: /app/data
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "200m"
      volumes:
        - name: marvin-data
          persistentVolumeClaim:
            claimName: marvin-data
```

## Deployment Procedure (Rolling Update with Downtime)

### Step 1: Pre-Deployment Backup

```bash
# Login to OpenShift
oc login <your-cluster-url>
oc project <your-project>

# Backup current database
POD=$(oc get pods -l app=marvin -o jsonpath='{.items[0].metadata.name}')
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Copy database from pod to local
oc exec $POD -- tar czf /tmp/backup-$TIMESTAMP.tar.gz /app/data
oc cp $POD:/tmp/backup-$TIMESTAMP.tar.gz ./marvin-backup-$TIMESTAMP.tar.gz

echo "Backup saved to: marvin-backup-$TIMESTAMP.tar.gz"
```

### Step 2: Build New Image

```bash
# Option A: Build from Git (if using BuildConfig)
oc start-build marvin --follow

# Option B: Build locally and push
docker build -f docker/Dockerfile --target production --tag marvin:latest .
docker tag marvin:latest <registry>/marvin:$(git rev-parse --short HEAD)
docker push <registry>/marvin:$(git rev-parse --short HEAD)

# Update ImageStream
oc tag <registry>/marvin:$(git rev-parse --short HEAD) marvin:latest
```

### Step 3: Tag Current Version as Stable (for easy rollback)

```bash
# Tag current running version as stable before updating
oc tag marvin:latest marvin:stable
```

### Step 4: Scale Down Application

```bash
# Scale to 0 to prevent database conflicts during migration
oc scale dc/marvin --replicas=0

# Wait for all pods to terminate
oc wait --for=delete pod -l app=marvin --timeout=120s
```

### Step 5: Run Database Migration

```bash
# Create a one-time migration job
cat <<EOF | oc create -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: marvin-migration-$(date +%Y%m%d-%H%M%S)
  labels:
    app: marvin
    job-type: migration
spec:
  template:
    metadata:
      labels:
        app: marvin
        job-type: migration
    spec:
      restartPolicy: OnFailure
      containers:
        - name: migration
          image: 'marvin:latest'
          command:
            - /bin/bash
            - -c
            - |
              set -e
              echo "Starting database migration..."
              cd /app/src/marvin

              # Show current migration status
              echo "Current status:"
              uv run alembic current

              # Run migration
              echo "Running upgrade..."
              uv run alembic upgrade head

              # Verify new status
              echo "New status:"
              uv run alembic current

              echo "Migration complete!"
          env:
            - name: PRODUCTION
              value: "true"
            - name: DB_ENGINE
              value: "sqlite"
            - name: DATA_DIR
              value: "/app/data"
          envFrom:
            - secretRef:
                name: marvin-secrets
            - configMapRef:
                name: marvin-config
          volumeMounts:
            - name: marvin-data
              mountPath: /app/data
      volumes:
        - name: marvin-data
          persistentVolumeClaim:
            claimName: marvin-data
EOF

# Watch migration job
MIGRATION_JOB=$(oc get jobs -l job-type=migration --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
oc logs -f job/$MIGRATION_JOB

# Verify migration succeeded
oc wait --for=condition=complete --timeout=300s job/$MIGRATION_JOB

# Check job status
oc get job $MIGRATION_JOB
```

### Step 6: Deploy New Version

```bash
# Trigger new deployment with latest image
oc rollout latest dc/marvin

# Or scale up if using existing deployment
oc scale dc/marvin --replicas=2

# Watch rollout
oc rollout status dc/marvin --watch
```

### Step 7: Verify Deployment

```bash
# Check pod status
oc get pods -l app=marvin

# Check logs for errors
POD=$(oc get pods -l app=marvin -o jsonpath='{.items[0].metadata.name}')
oc logs $POD | tail -100

# Test health endpoint
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
curl -v https://$ROUTE/api/health

# Verify database schema
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'
```

### Step 8: Verify New Features

```bash
# 1. Check state file exists
oc exec $POD -- cat /app/data/scheduler_state.json

# 2. Verify execution logs table exists
oc exec $POD -- bash -c 'cd /app && uv run python -c "
from marvin.db.db_setup import session_context
from marvin.db.models.groups import WebhookExecutionLogModel
with session_context() as session:
    count = session.query(WebhookExecutionLogModel).count()
    print(f\"Execution logs table exists, count: {count}\")
"'

# 3. Check token not in logs (trigger a token refresh first)
oc logs $POD | grep -i "token.*:" | head -20
# Should NOT see plaintext JWT tokens

# 4. Verify datetime field
oc exec $POD -- bash -c 'cd /app && uv run python -c "
from marvin.db.db_setup import session_context
from marvin.db.models.groups import GroupWebhooksModel
with session_context() as session:
    webhook = session.query(GroupWebhooksModel).first()
    if webhook:
        print(f\"scheduled_time type: {type(webhook.scheduled_time)}\")
        print(f\"scheduled_time value: {webhook.scheduled_time}\")
"'
```

### Step 9: Monitor for 24 Hours

```bash
# Set up log monitoring
oc logs -f dc/marvin --tail=100

# Watch for webhook execution logs
oc exec $POD -- bash -c 'watch -n 60 "cd /app && uv run python -c \"
from marvin.db.db_setup import session_context
from marvin.db.models.groups import WebhookExecutionLogModel
from datetime import datetime, timedelta, UTC
with session_context() as session:
    recent = session.query(WebhookExecutionLogModel).filter(
        WebhookExecutionLogModel.executed_at >= datetime.now(UTC) - timedelta(hours=1)
    ).count()
    print(f\\\"Webhook executions in last hour: {recent}\\\")
\""'
```

## Rollback Procedure

If issues are detected:

### Quick Rollback (Code Only)

```bash
# Rollback to stable version
oc tag marvin:stable marvin:latest --force
oc rollout latest dc/marvin

# Or rollback to previous deployment
oc rollout undo dc/marvin
oc rollout status dc/marvin --watch
```

### Full Rollback (Code + Database)

```bash
# 1. Scale down
oc scale dc/marvin --replicas=0

# 2. Restore database backup
POD=$(oc get pods -l app=marvin -o jsonpath='{.items[0].metadata.name}')
oc cp ./marvin-backup-$TIMESTAMP.tar.gz $POD:/tmp/
oc exec $POD -- tar xzf /tmp/marvin-backup-$TIMESTAMP.tar.gz -C /

# 3. Run downgrade migration
cat <<EOF | oc create -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: marvin-downgrade-$(date +%Y%m%d-%H%M%S)
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: downgrade
          image: 'marvin:stable'
          command:
            - /bin/bash
            - -c
            - cd /app/src/marvin && uv run alembic downgrade -1
          volumeMounts:
            - name: marvin-data
              mountPath: /app/data
      volumes:
        - name: marvin-data
          persistentVolumeClaim:
            claimName: marvin-data
EOF

# 4. Rollback code
oc tag marvin:stable marvin:latest --force
oc scale dc/marvin --replicas=2
```

## Blue/Green Deployment (Zero Downtime Alternative)

### Setup

```bash
# 1. Deploy green environment
oc new-app marvin:latest --name=marvin-green \
  --labels="app=marvin,version=green"

# 2. Apply same configuration
oc set env dc/marvin-green --from=configmap/marvin-config
oc set env dc/marvin-green --from=secret/marvin-secrets

# 3. Mount same PVC (WARNING: must stop blue for migration!)
oc set volume dc/marvin-green --add --name=marvin-data \
  --type=persistentVolumeClaim --claim-name=marvin-data \
  --mount-path=/app/data

# 4. Create green service (not exposed yet)
oc expose dc/marvin-green --port=8080 --name=marvin-green
```

### Cutover

```bash
# 1. Stop blue for migration
oc scale dc/marvin --replicas=0

# 2. Run migration (against shared PVC)
# ... (same as Step 5 above)

# 3. Start green
oc scale dc/marvin-green --replicas=2
oc rollout status dc/marvin-green

# 4. Test green internally
oc port-forward svc/marvin-green 8080:8080
curl http://localhost:8080/api/health

# 5. Switch route to green
oc patch route/marvin -p '{"spec":{"to":{"name":"marvin-green"}}}'

# 6. Monitor for issues
# If successful after 24h, delete blue:
oc delete dc/marvin
```

## Post-Deployment Validation

### Automated Tests

```bash
# Create a test script
cat > /tmp/test-deployment.sh <<'EOF'
#!/bin/bash
set -e

ROUTE=$1
BASE_URL="https://$ROUTE"

echo "Testing deployment at $BASE_URL"

# 1. Health check
echo "✓ Testing health endpoint..."
curl -f $BASE_URL/api/health

# 2. API docs (should be disabled in prod)
echo "✓ Verifying API docs disabled..."
! curl -f $BASE_URL/docs || echo "WARNING: API docs still enabled"

# 3. Create test webhook with datetime
echo "✓ Testing datetime webhooks..."
# Add your API test here

echo "All tests passed!"
EOF

chmod +x /tmp/test-deployment.sh

# Run tests
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
bash /tmp/test-deployment.sh $ROUTE
```

## Troubleshooting

### Migration Fails

```bash
# Check migration job logs
oc logs job/$MIGRATION_JOB

# Check database file permissions
POD=$(oc get pods -l app=marvin -o jsonpath='{.items[0].metadata.name}')
oc exec $POD -- ls -la /app/data/

# Manually inspect database
oc exec -it $POD -- bash
cd /app
uv run python -c "
from marvin.db.db_setup import session_context
from sqlalchemy import inspect
with session_context() as session:
    inspector = inspect(session.bind)
    print('Tables:', inspector.get_table_names())
"
```

### Pods Won't Start

```bash
# Check events
oc get events --sort-by='.lastTimestamp' | tail -20

# Check pod logs
oc logs $POD --previous  # If CrashLoopBackOff

# Check resource limits
oc describe pod $POD | grep -A 10 "Limits"
```

### State File Issues

```bash
# Check state file
oc exec $POD -- cat /app/data/scheduler_state.json

# Check permissions
oc exec $POD -- ls -la /app/data/

# Recreate if corrupted
oc exec $POD -- rm -f /app/data/scheduler_state.json
# Scheduler will recreate on next run
```

## Monitoring & Alerts

### Recommended Prometheus Metrics

Add these to your application (future enhancement):

```python
# Example metrics to add
webhook_executions_total{status="success|failed|retrying"}
webhook_retry_attempts_total
scheduler_state_load_failures_total
event_bus_token_exposure_attempts_total  # Should always be 0
```

### Log Aggregation Queries

```bash
# OpenShift logging (if enabled)
oc logs -l app=marvin --since=1h | grep "ERROR"
oc logs -l app=marvin --since=1h | grep "webhook.*failed"
oc logs -l app=marvin --since=1h | grep "retry"
```

## Performance Tuning

### Resource Limits

Based on your app's performance, adjust:

```yaml
resources:
  requests:
    memory: "256Mi"  # Minimum guaranteed
    cpu: "100m"
  limits:
    memory: "512Mi"  # Maximum allowed
    cpu: "500m"
```

### PVC Performance

If using many webhooks, consider faster storage class:

```bash
# Check available storage classes
oc get storageclass

# Update PVC (requires recreating)
# gp3, io1, etc. for better IOPS
```

## Security Considerations

1. **Secrets Management:** Use sealed-secrets or external secret management
2. **Network Policies:** Restrict egress for webhook calls if needed
3. **RBAC:** Limit service account permissions
4. **Image Scanning:** Scan images for vulnerabilities before deployment
5. **TLS:** Ensure route uses edge termination with valid certs

## Support & Maintenance

### Regular Tasks

- **Weekly:** Review webhook execution logs for failures
- **Monthly:** Prune old execution logs (add cleanup job)
- **Quarterly:** Review and optimize database
- **Annually:** Update dependencies and base images

### Backup Strategy

```bash
# Automated backup CronJob
cat <<EOF | oc create -f -
apiVersion: batch/v1
kind: CronJob
metadata:
  name: marvin-backup
spec:
  schedule: "0 2 * * *"  # 2 AM daily
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
                  TIMESTAMP=\$(date +%Y%m%d-%H%M%S)
                  tar czf /backups/marvin-\$TIMESTAMP.tar.gz /app/data
                  # Upload to S3/bucket here
              volumeMounts:
                - name: marvin-data
                  mountPath: /app/data
                - name: backups
                  mountPath: /backups
          restartPolicy: OnFailure
          volumes:
            - name: marvin-data
              persistentVolumeClaim:
                claimName: marvin-data
            - name: backups
              persistentVolumeClaim:
                claimName: marvin-backups
EOF
```

## Summary

This guide provides multiple deployment strategies for OpenShift:

1. **Rolling Update (Simpler):** For smaller deployments, accepts brief downtime
2. **Blue/Green (Production):** For zero-downtime cutover, requires extra resources
3. **Migration Job:** Safely runs database migrations
4. **Comprehensive Monitoring:** Validates deployment success
5. **Rollback Procedures:** Quick recovery if issues arise

Choose the strategy that best fits your availability requirements and resource constraints.
