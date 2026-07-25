# Marvin Helm Chart

Helm chart for deploying Marvin event bus application to Kubernetes/OpenShift.

## Overview

Marvin is an event bus application with webhook delivery, scheduling, and state persistence. This Helm chart provides:

- Automated database migrations on application startup
- API and server-rendered web UI from a single image, exposed on separate ports
- Multi-environment support (dev, staging, production)
- OpenShift Route integration
- Persistent storage for SQLite database
- Configurable resource limits
- Health checks and readiness probes

## Prerequisites

- Kubernetes 1.19+ or OpenShift 4.x+
- Helm 3.0+
- PersistentVolume provisioner support (for SQLite data)
- Container registry access (for pulling Marvin image)

## Installation

### Quick Start (Development)

```bash
# Install with default development values
helm install marvin ./marvin-chart

# Or specify namespace
helm install marvin ./marvin-chart --namespace marvin-dev --create-namespace
```

### Staging Deployment

```bash
helm install marvin ./marvin-chart \
  --namespace marvin-staging \
  --create-namespace \
  --values marvin-chart/values-staging.yaml \
  --set image.tag=$(git rev-parse --short HEAD)
```

### Production Deployment

```bash
helm upgrade --install marvin ./marvin-chart \
  --namespace marvin-prod \
  --create-namespace \
  --values marvin-chart/values-production.yaml \
  --set image.tag=$(git rev-parse --short HEAD) \
  --wait \
  --timeout 15m \
  --atomic
```

## Configuration

### Values Files

The chart includes three values files for different environments:

- **values.yaml** - Development defaults (1 replica, debug logging, local SMTP)
- **values-staging.yaml** - Staging overrides (2 replicas, info logging)
- **values-production.yaml** - Production settings (2+ replicas, strict security)

### Key Configuration Options

#### Image Settings

```yaml
image:
  repository: marvin
  pullPolicy: IfNotPresent
  tag: "latest"
```

#### Application Configuration

```yaml
config:
  production: false          # Enable production mode
  allowSignup: true          # Allow user signups
  logLevel: DEBUG            # Logging level (DEBUG, INFO, WARNING, ERROR)
  dbEngine: sqlite           # Database engine
  dataDir: /app/data         # Data directory for SQLite
  apiPort: 8080              # API server port
  webhookRetryAttempts: 3    # Webhook retry count
  webhookTimeout: 30         # Webhook timeout in seconds
```

#### Resource Limits

```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

#### Persistence

```yaml
persistence:
  enabled: true
  size: 10Gi
  storageClass: ""           # Empty = cluster default
  accessMode: ReadWriteOnce
```

#### OpenShift Route

```yaml
route:
  enabled: true
  host: ""                   # Auto-generated if empty
  tls:
    enabled: true
    termination: edge
```

### Secrets Management

**Development:** Secrets can be specified in values.yaml

**Production:** Use sealed-secrets or external secret management:

```bash
# Create sealed secret
kubectl create secret generic marvin-secrets \
  --from-literal=SMTP_HOST=smtp.example.com \
  --from-literal=SMTP_PORT=587 \
  --from-literal=JWT_SECRET=your-secret-here \
  --dry-run=client -o yaml | \
  kubeseal -o yaml > marvin-chart/templates/sealed-secret.yaml

# Then disable default secret in values-production.yaml
# and reference the sealed secret in deployment
```

## Deployment Modes

The chart runs Marvin in one of two topologies, chosen with `mode`:

- **`combined`** (default) — one Deployment whose container runs the API and the server-rendered
  frontend together (via the `marvin` image). Simplest to operate; the API and UI scale and roll as
  a unit.
- **`split`** — two Deployments, the API (`marvin-backend` image) and the frontend (`marvin-frontend`
  image), each with its own Service, scaled and rolled independently. The frontend reaches the API
  over the in-cluster `<release>-backend` Service; the public route points at the frontend. Use this
  when you want to scale the stateless UI separately from the API, or roll one without restarting the
  other.

```yaml
# split mode
mode: split
split:
  backend:
    replicaCount: 2
  frontend:
    replicaCount: 3
# The browser-facing API URL must be set so injected pages can reach the API from outside the
# cluster (the API is otherwise only on an internal Service):
config:
  publicApiUrl: https://marvin.example.com
```

The backend and frontend images default to `<image.repository>-backend` / `-frontend` at
`image.tag`; override `split.backend.image` / `split.frontend.image` for a different registry. Both
images come from the same build as the combined one — see the Dockerfile's `backend` and `frontend`
targets.

## Database Migrations

The application runs `alembic upgrade head` itself during startup, before it begins serving. The
chart does not schedule a separate migration Job — one less moving part, and it keeps the schema in
lockstep with the image that owns it.

Because migrations are part of startup, the readiness probe (`/readyz`) is what gates traffic: a pod
stays out of the Service until its schema is current and the database answers. Give `--timeout`
enough room on upgrades that introduce long migrations.

To watch a migration:

```bash
kubectl logs -f deployment/marvin -n <namespace>
```

## Integration Plugins

Marvin core ships no integration providers. It discovers them through the `marvin.integrations`
entry-point group, read from installed distribution metadata when the process starts. Three
consequences worth knowing before you pick an approach:

- A provider has to be a real installed distribution. A loose `.py` file on a volume registers
  nothing, because there is no `dist-info` to read an entry point from.
- Whether the integrations API surface exists at all is decided at import. With no provider
  installed, the `marvin_integration_sdk` package is absent and those routes are never registered.
- Adding or removing a plugin therefore requires a pod restart. Nothing is hot-loaded.

### Recommended: a derived image

Pin the plugin set into an image and let the tag describe it. Dependency conflicts surface as a
build failure rather than an import error in a running pod, and the deployment stays immutable.

```dockerfile
FROM ghcr.io/inneropen/marvin:1.0.0-rc.10
RUN /app/.venv/bin/pip install marvin-integration-slack
```

```yaml
image:
  repository: ghcr.io/your-org/marvin-with-slack
  tag: "1.0.0-rc.10"
```

### Without rebuilding: an init container plus PYTHONPATH

If you need to add a provider against a stock image, install it into a shared volume and put that
volume on `PYTHONPATH`. Entry points are discovered from any `sys.path` entry, so this is enough for
the loader to find the plugin.

```yaml
initContainers:
  - name: install-plugins
    image: python:3.12-slim
    command: ["sh", "-c", "pip install --target /plugins marvin-integration-slack"]
    volumeMounts:
      - name: plugins
        mountPath: /plugins

extraVolumes:
  - name: plugins
    emptyDir: {}

extraVolumeMounts:
  - name: plugins
    mountPath: /plugins

extraEnv:
  - name: PYTHONPATH
    value: /plugins
```

Two things to watch. `pip install --target` resolves nothing against the venv already in the image,
so the plugin's transitive dependencies have to land in `/plugins` too. And `PYTHONPATH` is searched
before site-packages, so anything vendored there shadows the image's own copy — pin versions
deliberately. An `emptyDir` also means the install re-runs on every pod start, which needs egress to
your package index; swap in a PVC if you would rather do it once.

## Upgrading

### Standard Upgrade

```bash
# Production upgrade with automatic migration
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml \
  --set image.tag=$(git rev-parse --short HEAD) \
  --wait \
  --timeout 15m \
  --atomic
```

### Dry Run (Preview Changes)

```bash
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml \
  --set image.tag=new-version \
  --dry-run --debug
```

### Breaking Schema Changes

For breaking migrations (like TIME → DATETIME conversion):

1. **Backup first:**
   ```bash
   POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
   oc exec $POD -- tar czf /tmp/backup.tar.gz /app/data
   oc cp $POD:/tmp/backup.tar.gz ./marvin-backup-$(date +%Y%m%d).tar.gz
   ```

2. **Run upgrade** (migration happens automatically as the new pod starts)

3. **Verify** migration success before traffic resumes

## Rollback

### Quick Rollback (Code Only)

```bash
# View release history
helm history marvin -n marvin-prod

# Rollback to previous release
helm rollback marvin -n marvin-prod

# Or rollback to specific revision
helm rollback marvin 3 -n marvin-prod
```

### Full Rollback (Code + Database)

If data corruption or migration issues occur:

```bash
# 1. Scale down application
oc scale deployment/marvin --replicas=0

# 2. Restore database backup (see ROLLBACK_PROCEDURES.md)

# 3. Rollback Helm release
helm rollback marvin -n marvin-prod
```

See `ROLLBACK_PROCEDURES.md` for detailed rollback instructions.

## Monitoring

### Health Checks

```bash
# Get route URL
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')

# Check health endpoint
curl -v https://$ROUTE/healthz
```

### View Logs

```bash
# Get pod name
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')

# Tail logs
oc logs -f $POD

# Check for errors
oc logs $POD | grep ERROR
```

### Verify Migration Status

```bash
oc exec $POD -- alembic -c /app/.venv/lib/python3.12/site-packages/marvin/alembic.ini current
```

Or simply read it off the startup log — the application logs its migration run before serving.

### Check Scheduler State

```bash
oc exec $POD -- cat /app/data/scheduler_state.json
```

## Troubleshooting

### Migration Failed

Migrations run inside the application pod at startup, so a failure shows up as a pod that never
becomes ready:

```bash
# The migration output is at the top of the startup log
kubectl logs -n <namespace> deployment/marvin | head -50

# If the pod already restarted, read the previous container's log
kubectl logs -n <namespace> $POD --previous
```

### Pod CrashLoopBackOff

```bash
# Check pod logs
oc logs $POD --previous

# Check events
oc get events --sort-by='.lastTimestamp'

# Describe pod
oc describe pod $POD
```

### PVC Not Mounting

```bash
# Check PVC status
oc get pvc

# Check PVC events
oc describe pvc marvin-data

# Verify storage class
oc get sc
```

## Uninstalling

```bash
# Uninstall release (keeps PVC by default)
helm uninstall marvin -n marvin-prod

# Delete PVC manually if needed
oc delete pvc marvin-data
```

## Chart Development

### Linting

```bash
helm lint ./marvin-chart
```

### Template Rendering

```bash
helm template marvin ./marvin-chart \
  --values marvin-chart/values-production.yaml \
  --set image.tag=test
```

### Packaging

```bash
helm package ./marvin-chart
```

## Support

For issues and questions:
- GitHub: https://github.com/InnerOpen/marvin/issues
- Documentation: See `HELM_DEPLOYMENT_GUIDE.md`
- Rollback procedures: See `ROLLBACK_PROCEDURES.md`

## License

[Your License]
