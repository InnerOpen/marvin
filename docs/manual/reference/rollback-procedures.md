# Marvin Rollback Procedures

Comprehensive rollback procedures for various failure scenarios when deploying Marvin with Helm.

## Table of Contents

- [Quick Reference](#quick-reference)
- [Rollback Decision Tree](#rollback-decision-tree)
- [Procedure 1: Quick Helm Rollback (Code Only)](#procedure-1-quick-helm-rollback-code-only)
- [Procedure 2: Full Rollback (Code + Database)](#procedure-2-full-rollback-code-database)
- [Procedure 3: Emergency Rollback (Production Down)](#procedure-3-emergency-rollback-production-down)
- [Procedure 4: Partial Rollback (Configuration Only)](#procedure-4-partial-rollback-configuration-only)
- [Recovery Scenarios](#recovery-scenarios)
- [Testing Rollback](#testing-rollback)
- [Post-Rollback Actions](#post-rollback-actions)

---

## Quick Reference

| Scenario | Procedure | Data Loss Risk | Downtime |
|----------|-----------|----------------|----------|
| Code bug, no DB changes | Quick Helm Rollback | None | ~2 min |
| Migration issue, no data written | Quick Helm + manual downgrade | None | ~5 min |
| Data corruption | Full Rollback | Logs since deployment | ~10-15 min |
| Production completely down | Emergency Rollback | Possibly high | ~5 min |
| Config error only | Configuration Rollback | None | ~1 min |

---

## Rollback Decision Tree

```
Deployment failed or issues detected
    │
    ├─ Is production completely down?
    │   └─ YES → Emergency Rollback (Procedure 3)
    │
    ├─ Did migration run successfully?
    │   ├─ NO → Quick Helm Rollback (Procedure 1)
    │   └─ YES → Continue
    │
    ├─ Is there data corruption or loss?
    │   ├─ YES → Full Rollback (Procedure 2)
    │   └─ NO → Continue
    │
    ├─ Is it just a configuration issue?
    │   ├─ YES → Configuration Rollback (Procedure 4)
    │   └─ NO → Continue
    │
    └─ Is the bug in code, not data?
        ├─ YES → Quick Helm Rollback (Procedure 1)
        └─ NO → Assess and choose appropriate procedure
```

---

## Procedure 1: Quick Helm Rollback (Code Only)

**Use when:**
- Application code has bugs but database is fine
- Migration failed and no schema changes were applied
- Configuration issue but database is intact
- No data corruption or loss

**Risks:**
- Low risk, reversible
- Database migration NOT automatically reversed

**Estimated Downtime:** 2-5 minutes

### Steps

```bash
# 1. Verify Helm release history
helm history marvin -n marvin-prod

# Output example:
# REVISION  UPDATED                   STATUS      CHART          APP VERSION  DESCRIPTION
# 1         Wed Jun 4 10:00:00 2026   superseded  marvin-1.0.0   2026.06.04   Install complete
# 2         Thu Jun 5 14:30:00 2026   deployed    marvin-1.1.0   2026.06.05   Upgrade complete

# 2. Check current deployment status
helm status marvin -n marvin-prod

# 3. Rollback to previous revision
helm rollback marvin -n marvin-prod

# Or rollback to specific revision:
# helm rollback marvin 1 -n marvin-prod

# 4. Monitor rollback
oc rollout status deployment/marvin --watch

# 5. Verify pods are running
oc get pods -l app.kubernetes.io/name=marvin

# 6. Check application logs
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc logs $POD --tail=50

# 7. Verify health endpoint
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
curl -v https://$ROUTE/api/health

# 8. Confirm rollback success
helm history marvin -n marvin-prod
```

### What Helm Rollback Does

- ✅ Reverts Deployment to previous image tag
- ✅ Restores previous ConfigMap values
- ✅ Restores previous Secret values (if changed)
- ✅ Rolls back Service/Route changes
- ❌ Does NOT reverse database migrations
- ❌ Does NOT restore data

### If Database Migration Needs Reversal

If the migration ran but needs to be reversed:

```bash
# 1. Scale down to prevent database access
oc scale deployment/marvin --replicas=0
oc wait --for=delete pod -l app.kubernetes.io/name=marvin --timeout=120s

# 2. Create downgrade job
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
          image: marvin:stable  # Use previous stable image
          command:
            - /bin/bash
            - -c
            - |
              set -e
              cd /app/src/marvin
              echo "Current migration:"
              uv run alembic current
              echo "Downgrading one revision..."
              uv run alembic downgrade -1
              echo "New migration status:"
              uv run alembic current
          volumeMounts:
            - name: data
              mountPath: /app/data
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: marvin-data
EOF

# 3. Monitor downgrade job
DOWNGRADE_JOB=$(oc get jobs --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
oc logs -f job/$DOWNGRADE_JOB

# 4. Wait for completion
oc wait --for=condition=complete --timeout=300s job/$DOWNGRADE_JOB

# 5. Scale back up
oc scale deployment/marvin --replicas=2

# 6. Verify
oc get pods
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'
```

---

## Procedure 2: Full Rollback (Code + Database)

**Use when:**
- Data corruption detected
- Migration applied incorrectly
- Need to restore to exact previous state
- Database schema and data both need reversal

**Risks:**
- Loses all data written since deployment
- Loses webhook execution logs created after deployment
- Time-consuming

**Estimated Downtime:** 10-15 minutes

### Prerequisites

- Recent database backup exists
- Backup has been tested (restore verified)
- Maintenance window scheduled
- Users notified

### Steps

#### Phase 1: Stop Application

```bash
# 1. Switch to production namespace
oc project marvin-prod

# 2. Record current state for post-mortem
helm status marvin -n marvin-prod > /tmp/rollback-state-$(date +%Y%m%d-%H%M%S).txt
oc get pods -o yaml > /tmp/rollback-pods-$(date +%Y%m%d-%H%M%S).yaml

# 3. Scale down to zero (stop all traffic)
oc scale deployment/marvin --replicas=0

# 4. Wait for all pods to terminate
oc wait --for=delete pod -l app.kubernetes.io/name=marvin --timeout=120s

# 5. Verify no pods running
oc get pods -l app.kubernetes.io/name=marvin
# Should show: No resources found
```

#### Phase 2: Restore Database

```bash
# 1. List available backups
ls -lh marvin-backup-*.tar.gz

# Example:
# marvin-backup-20260605-140000.tar.gz  (pre-deployment backup)
# marvin-backup-20260604-020000.tar.gz  (previous day's backup)

# 2. Choose the correct backup
BACKUP_FILE="marvin-backup-20260605-140000.tar.gz"
echo "Using backup: $BACKUP_FILE"

# 3. Verify backup integrity
tar tzf $BACKUP_FILE | head -20

# 4. Create temporary restore pod
cat <<EOF | oc create -f -
apiVersion: v1
kind: Pod
metadata:
  name: marvin-restore
  labels:
    app: marvin-restore
spec:
  restartPolicy: Never
  containers:
    - name: restore
      image: marvin:stable
      command:
        - /bin/bash
        - -c
        - sleep 3600
      volumeMounts:
        - name: data
          mountPath: /app/data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: marvin-data
EOF

# 5. Wait for restore pod to be ready
oc wait --for=condition=ready pod/marvin-restore --timeout=60s

# 6. Backup current data (just in case)
SAFETY_BACKUP="marvin-safety-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
oc exec marvin-restore -- tar czf /tmp/safety.tar.gz /app/data
oc cp marvin-restore:/tmp/safety.tar.gz ./$SAFETY_BACKUP
echo "Safety backup saved: $SAFETY_BACKUP"

# 7. Clear current data directory
oc exec marvin-restore -- bash -c 'rm -rf /app/data/*'

# 8. Copy backup to restore pod
oc cp ./$BACKUP_FILE marvin-restore:/tmp/backup.tar.gz

# 9. Restore data
oc exec marvin-restore -- bash -c 'cd / && tar xzf /tmp/backup.tar.gz'

# 10. Verify restore
oc exec marvin-restore -- ls -lh /app/data

# 11. Delete restore pod
oc delete pod marvin-restore
```

#### Phase 3: Rollback Application

```bash
# 1. Rollback Helm release to previous version
helm rollback marvin -n marvin-prod

# Or to specific revision if needed:
# helm rollback marvin 1 -n marvin-prod

# 2. Monitor rollback
oc get pods -w

# 3. Wait for pods to be ready
oc wait --for=condition=ready pod -l app.kubernetes.io/name=marvin --timeout=300s

# 4. Verify deployment
oc rollout status deployment/marvin
```

#### Phase 4: Verification

```bash
# 1. Get new pod
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')

# 2. Check application logs
oc logs $POD --tail=100

# 3. Verify migration version
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'

# 4. Verify database integrity
oc exec $POD -- bash -c 'cd /app && uv run python -c "
from marvin.db.db_setup import session_context
from marvin.db.models.groups import GroupWebhooksModel
with session_context() as session:
    count = session.query(GroupWebhooksModel).count()
    print(f\"Webhooks count: {count}\")
"'

# 5. Test health endpoint
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
curl -v https://$ROUTE/api/health

# 6. Verify Helm release
helm history marvin -n marvin-prod
helm status marvin -n marvin-prod

# 7. Test basic functionality
# - Login to application
# - List webhooks
# - Create test webhook
# - Verify scheduler runs
```

---

## Procedure 3: Emergency Rollback (Production Down)

**Use when:**
- Production is completely down
- Users cannot access the application
- Need fastest possible recovery
- Can investigate root cause later

**Estimated Downtime:** 5-10 minutes

### Steps

```bash
# 1. Quick status check
oc project marvin-prod
oc get pods
helm status marvin -n marvin-prod

# 2. Immediate rollback (don't investigate yet)
helm rollback marvin -n marvin-prod

# 3. If rollback fails or pods still not starting, force restart
oc scale deployment/marvin --replicas=0
oc scale deployment/marvin --replicas=2

# 4. If still down, rollback to known-good revision
helm history marvin -n marvin-prod
# Identify last known-good revision (e.g., revision 3)
helm rollback marvin 3 -n marvin-prod

# 5. If STILL down, check for PVC issues
oc get pvc
oc describe pvc marvin-data
# If PVC is the issue, may need to restore from backup

# 6. Monitor recovery
oc get pods -w

# 7. Once pods running, verify health
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc logs $POD --tail=50
ROUTE=$(oc get route marvin -o jsonpath='{.spec.host}')
curl -v https://$ROUTE/api/health

# 8. Notify stakeholders of recovery

# 9. After service restored, investigate root cause
oc get events --sort-by='.lastTimestamp' | tail -50
helm get all marvin -n marvin-prod
```

---

## Procedure 4: Partial Rollback (Configuration Only)

**Use when:**
- Code is fine, configuration values are wrong
- Environment variables misconfigured
- Resource limits too low/high
- No code or schema changes needed

**Estimated Downtime:** 1-2 minutes (rolling update)

### Steps

```bash
# 1. Identify configuration issue
oc get configmap marvin -o yaml
oc get secret marvin -o yaml

# 2. Option A: Rollback entire release
helm rollback marvin -n marvin-prod

# 3. Option B: Fix configuration in place
# Edit values file
vim marvin-chart/values-production.yaml

# Apply updated configuration
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml \
  --reuse-values

# 4. Monitor rolling update
oc rollout status deployment/marvin --watch

# 5. Verify configuration
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc exec $POD -- env | grep -E "PRODUCTION|LOG_LEVEL|API_PORT"

# 6. Verify application still healthy
oc logs $POD --tail=50
```

---

## Recovery Scenarios

### Scenario 1: Migration Failed, Pods Won't Start

**Symptoms:**
- Migration job failed
- Pods stuck in CrashLoopBackOff
- Database in inconsistent state

**Recovery:**

```bash
# 1. Check migration job logs
MIGRATION_JOB=$(oc get jobs -l job-type=migration --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
oc logs job/$MIGRATION_JOB

# 2. Delete failed migration job
oc delete job $MIGRATION_JOB

# 3. If migration was partially applied, manual intervention needed
# Create manual downgrade job (see Procedure 1)

# 4. Once database is stable, rollback Helm release
helm rollback marvin -n marvin-prod

# 5. Verify recovery
oc get pods
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc exec $POD -- bash -c 'cd /app/src/marvin && uv run alembic current'
```

### Scenario 2: Data Corruption Detected After Deployment

**Symptoms:**
- Webhooks missing or incorrect
- Execution logs corrupted
- Scheduler state file invalid

**Recovery:**

Use **Procedure 2: Full Rollback (Code + Database)**

Additionally:

```bash
# After restore, verify data integrity
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')

# Check webhooks table
oc exec $POD -- bash -c 'cd /app && uv run python -c "
from marvin.db.db_setup import session_context
from marvin.db.models.groups import GroupWebhooksModel
with session_context() as session:
    webhooks = session.query(GroupWebhooksModel).all()
    print(f\"Total webhooks: {len(webhooks)}\")
    for w in webhooks[:5]:
        print(f\"  - {w.id}: {w.scheduled_time}\")
"'

# Verify scheduler state
oc exec $POD -- cat /app/data/scheduler_state.json
```

### Scenario 3: Performance Degradation After Deployment

**Symptoms:**
- Application running but slow
- High memory/CPU usage
- Timeouts on API requests

**Recovery:**

```bash
# 1. Check resource usage
oc adm top pods

# 2. Check for resource limits
oc describe deployment marvin | grep -A 10 Limits

# 3. If resource issue, quick config update
# Edit values to increase limits
vim marvin-chart/values-production.yaml

# Increase resources:
# resources:
#   limits:
#     memory: "2Gi"  # was 1Gi
#     cpu: "2000m"   # was 1000m

# Apply
helm upgrade marvin ./marvin-chart \
  --namespace marvin-prod \
  --values marvin-chart/values-production.yaml

# 4. If not resource issue, rollback code
helm rollback marvin -n marvin-prod

# 5. Investigate root cause
oc logs deployment/marvin --tail=500 > /tmp/performance-logs.txt
```

### Scenario 4: Scheduler Stopped Working

**Symptoms:**
- Webhooks not firing
- scheduler_state.json not updating
- No scheduler logs

**Recovery:**

```bash
# 1. Check if scheduler is running
POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc logs $POD | grep -i scheduler | tail -20

# 2. Check scheduler state file
oc exec $POD -- cat /app/data/scheduler_state.json

# 3. Restart pod
oc delete pod $POD
oc wait --for=condition=ready pod -l app.kubernetes.io/name=marvin --timeout=120s

# 4. If still not working, rollback
helm rollback marvin -n marvin-prod

# 5. Verify scheduler starts
NEW_POD=$(oc get pods -l app.kubernetes.io/name=marvin -o jsonpath='{.items[0].metadata.name}')
oc logs $NEW_POD | grep -i scheduler
```

---

## Testing Rollback

**Before production deployment, test rollback procedure:**

### In Dev

```bash
# 1. Deploy to dev (marvin-dev)
helm upgrade --install marvin ./marvin-chart \
  --namespace marvin-dev \
  --values marvin-chart/values-dev.yaml \
  --set image.tag=test-version

# 2. Verify deployment works
# ... run tests ...

# 3. Practice rollback
helm rollback marvin -n marvin-dev

# 4. Verify rollback works
# ... run tests ...

# 5. Practice full rollback with database restore
# ... follow Procedure 2 ...

# 6. Document any issues found
```

### Rollback Drill Checklist

- [ ] Quick Helm rollback completes in < 3 minutes
- [ ] Pods restart successfully after rollback
- [ ] Application health check passes after rollback
- [ ] Database downgrade job works correctly
- [ ] Backup restore procedure tested and timed
- [ ] All team members know rollback commands
- [ ] Emergency contacts list updated
- [ ] Rollback runbook accessible during incident

---

## Post-Rollback Actions

After successful rollback:

### Immediate (Within 1 hour)

1. **Verify Stability**
   ```bash
   # Monitor for 30 minutes
   watch -n 30 'oc get pods && oc adm top pods'
   ```

2. **Notify Stakeholders**
   - Deployment rolled back
   - Service restored
   - Root cause investigation started

3. **Preserve Evidence**
   ```bash
   # Save logs from failed deployment
   oc logs -l app.kubernetes.io/name=marvin --all-containers > /tmp/rollback-logs-$(date +%Y%m%d-%H%M%S).txt

   # Save Helm state
   helm get all marvin -n marvin-prod > /tmp/rollback-helm-$(date +%Y%m%d-%H%M%S).yaml
   ```

### Short-term (Within 24 hours)

1. **Root Cause Analysis**
   - What went wrong?
   - Why did it go wrong?
   - Why didn't we catch it before production?

2. **Document Incident**
   - Timeline of events
   - Commands executed
   - Data lost (if any)
   - Recovery time

3. **Update Runbooks**
   - Add new failure mode to this document
   - Update deployment checklist
   - Improve pre-deployment verification

### Long-term (Within 1 week)

1. **Improve Testing**
   - Add tests for the failure scenario
   - Update dev (marvin-dev) to match production
   - Automate rollback testing

2. **Improve Monitoring**
   - Add alerts for early detection
   - Improve health checks
   - Add canary deployment if needed

3. **Team Review**
   - Blameless post-mortem
   - Share learnings
   - Update team procedures

---

## Rollback Checklist Template

Use this checklist during actual rollback:

```markdown
## Rollback Incident: [Date] [Time]

**Incident Reporter:**
**Severity:** [P0/P1/P2]
**Affected Service:** Marvin Production
**Decision to Rollback:** [Time] by [Name]

### Pre-Rollback
- [ ] Incident severity assessed
- [ ] Rollback decision maker identified
- [ ] Users notified of degradation
- [ ] Backup verification confirmed
- [ ] Rollback procedure selected: [1/2/3/4]

### During Rollback
- [ ] Start time recorded: ___:___
- [ ] Application scaled down
- [ ] Database backup restored (if needed)
- [ ] Helm release rolled back
- [ ] Pods restarted successfully
- [ ] Health checks passing
- [ ] End time recorded: ___:___
- [ ] Total downtime: ___ minutes

### Post-Rollback Verification
- [ ] Health endpoint: OK
- [ ] Database integrity: OK
- [ ] Scheduler running: OK
- [ ] Webhooks processing: OK
- [ ] No errors in logs
- [ ] Resource usage normal
- [ ] Users notified of recovery

### Follow-up
- [ ] Logs preserved
- [ ] Incident documented
- [ ] Root cause identified
- [ ] Fix planned
- [ ] Prevention measures identified
- [ ] Team debrief scheduled
```

---

## Emergency Contacts

**Update with your team's contacts:**

- **On-Call Engineer:** [Name] [Phone] [Slack]
- **Engineering Manager:** [Name] [Phone] [Slack]
- **Database Admin:** [Name] [Phone] [Slack]
- **Platform Team:** [Slack Channel]
- **Status Page:** [URL]

---

## Additional Resources

- **Helm Rollback Docs**: https://helm.sh/docs/helm/helm_rollback/
- **OpenShift Rollback**: https://docs.openshift.com/container-platform/latest/applications/deployments/deployment-strategies.html
- **Deployment Guide**: [Helm deployment guide](helm-deployment-guide.md)
- **Chart README**: See `marvin-chart/README.md`

---

**Remember:**
- Don't panic
- Follow the procedure
- Communicate with team
- Preserve evidence
- Learn from incidents
