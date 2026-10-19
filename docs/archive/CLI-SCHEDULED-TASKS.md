# Scheduled Tasks CLI Guide

The Marvin CLI provides complete command-line management for scheduled tasks.

## Installation

```bash
npm install -g marvin-cli
# or
yarn global add marvin-cli
```

## Authentication

All commands require authentication via user token:

```bash
# Set environment variable
export MARVIN_USER_TOKEN="your-token-here"

# Or pass inline
marvinctl platform scheduled-tasks list --user-token "your-token-here"
```

## Commands

### List Tasks

```bash
# List all tasks
marvinctl platform scheduled-tasks list

# Alias (shorter)
marvinctl platform tasks list

# Show only enabled tasks
marvinctl platform tasks list --enabled-only

# Show only failed tasks
marvinctl platform tasks list --failed-only

# Output formats
marvinctl platform tasks list --output table   # Default
marvinctl platform tasks list --output json
marvinctl platform tasks list --output yaml
marvinctl platform tasks list --output csv
```

**Example output:**
```
┌──────────────────────────────────────┬─────────────────┬─────────────────────┬───────────────┬─────────┬─────────────┬─────────────────────┐
│ id                                   │ name            │ task_type           │ schedule_type │ enabled │ last_status │ next_run_at         │
├──────────────────────────────────────┼─────────────────┼─────────────────────┼───────────────┼─────────┼─────────────┼─────────────────────┤
│ 550e8400-e29b-41d4-a716-446655440000 │ Daily Cleanup   │ cleanup_temp_files  │ interval      │ true    │ success     │ 2026-07-10T02:00:00 │
│ 550e8400-e29b-41d4-a716-446655440001 │ Hourly Publish  │ publish_scheduled   │ cron          │ true    │ success     │ 2026-07-09T15:00:00 │
└──────────────────────────────────────┴─────────────────┴─────────────────────┴───────────────┴─────────┴─────────────┴─────────────────────┘
```

### Get Task Details

```bash
# By ID
marvinctl platform tasks get 550e8400-e29b-41d4-a716-446655440000

# By slug
marvinctl platform tasks get daily-cleanup

# JSON output for scripting
marvinctl platform tasks get daily-cleanup --output json
```

### Create Task

**From JSON file:**

```bash
# Create task definition
cat > task.json <<EOF
{
  "name": "Daily Cleanup",
  "description": "Clean up old temp files every day",
  "task_type": "cleanup_temp_files",
  "schedule_type": "interval",
  "schedule_config": {
    "interval_seconds": 86400
  },
  "task_config": {
    "age_hours": 24,
    "dry_run": false
  },
  "enabled": true
}
EOF

# Create task
marvinctl platform tasks create --file task.json
```

**From inline JSON:**

```bash
marvinctl platform tasks create --json '{
  "name": "Hourly Publish",
  "task_type": "publish_scheduled_entries",
  "schedule_type": "cron",
  "schedule_config": {
    "cron_expression": "0 * * * *",
    "timezone": "America/New_York"
  },
  "enabled": true
}'
```

**Schedule types:**

1. **Interval** - Run every N seconds
   ```json
   {
     "schedule_type": "interval",
     "schedule_config": {
       "interval_seconds": 3600
     }
   }
   ```

2. **Cron** - Cron expression
   ```json
   {
     "schedule_type": "cron",
     "schedule_config": {
       "cron_expression": "0 2 * * *",
       "timezone": "UTC"
     }
   }
   ```

3. **Once** - Run at specific datetime
   ```json
   {
     "schedule_type": "once",
     "schedule_config": {
       "run_at": "2026-12-25T00:00:00Z"
     }
   }
   ```

### Update Task

```bash
# Update from file
marvinctl platform tasks update daily-cleanup --file updated-task.json

# Update from inline JSON
marvinctl platform tasks update daily-cleanup --json '{"description": "New description"}'

# Quick enable/disable
marvinctl platform tasks update daily-cleanup --enable
marvinctl platform tasks update daily-cleanup --disable
```

### Delete Task

```bash
# Delete (requires confirmation)
marvinctl platform tasks delete daily-cleanup --yes
```

### Run Task Manually

Trigger immediate execution, bypassing the schedule:

```bash
# Execute task now
marvinctl platform tasks run daily-cleanup

# Alias
marvinctl platform tasks execute daily-cleanup
```

**Output:**
```
✓ Task execution triggered: daily-cleanup
Check 'history' command for execution results
```

### View Execution History

```bash
# Last 50 executions (default)
marvinctl platform tasks history daily-cleanup

# Custom limit
marvinctl platform tasks history daily-cleanup --limit 100

# Show only failures
marvinctl platform tasks history daily-cleanup --failed-only

# Export to JSON for analysis
marvinctl platform tasks history daily-cleanup --output json > history.json
```

**Example output:**
```
┌─────────────────────┬─────────┬─────────────┬───────────────────────────┬───────────────┐
│ executed_at         │ status  │ duration_ms │ error_message             │ retry_attempt │
├─────────────────────┼─────────┼─────────────┼───────────────────────────┼───────────────┤
│ 2026-07-09T14:30:00 │ success │ 1234        │                           │ 0             │
│ 2026-07-09T13:30:00 │ success │ 1189        │                           │ 0             │
│ 2026-07-09T12:30:00 │ failed  │ 5678        │ Storage unavailable       │ 0             │
│ 2026-07-09T11:30:00 │ success │ 1456        │                           │ 0             │
└─────────────────────┴─────────┴─────────────┴───────────────────────────┴───────────────┘
```

### Discover Task Types

```bash
# Simple list
marvinctl platform tasks types

# With descriptions and config schemas
marvinctl platform tasks types --detailed
```

**Example output (simple):**
```
Available task types:
  - cleanup_temp_files
  - publish_scheduled_entries
  - unpublish_expired_entries
  - prune_expired_sessions
  - remove_orphaned_assets

Use --detailed for metadata and config schemas
```

**Example output (detailed):**
```
┌─────────────────────────────┬──────────────────────────┬───────────────────────────────────────┐
│ task_type                   │ name                     │ description                           │
├─────────────────────────────┼──────────────────────────┼───────────────────────────────────────┤
│ cleanup_temp_files          │ Cleanup Temporary Files  │ Remove old files from temp storage    │
│ publish_scheduled_entries   │ Publish Scheduled Entries│ Publish entries at scheduled time     │
│ prune_expired_sessions      │ Prune Expired Sessions   │ Remove expired user sessions          │
└─────────────────────────────┴──────────────────────────┴───────────────────────────────────────┘
```

### Task Statistics

Quick health check across all tasks:

```bash
marvinctl platform tasks stats
```

**Example output:**
```
Scheduled Task Statistics:
  Total tasks:       12
  Enabled:           10
  Disabled:          2
  Never run:         1
  Last status:
    Success:         8
    Failed:          3

⚠️  Some tasks have failed. Run 'list --failed-only' to see them.
```

## Common Workflows

### Monitor Failed Tasks

```bash
# Check stats
marvinctl platform tasks stats

# List failed tasks
marvinctl platform tasks list --failed-only

# Get details on failed task
marvinctl platform tasks get <task-id>

# View failure history
marvinctl platform tasks history <task-id> --failed-only

# Disable failed task for investigation
marvinctl platform tasks update <task-id> --disable
```

### Create and Test Task

```bash
# 1. Discover available task types
marvinctl platform tasks types --detailed

# 2. Create task
marvinctl platform tasks create --file task.json

# 3. Manually trigger to test
marvinctl platform tasks run <task-id>

# 4. Check execution result
marvinctl platform tasks history <task-id> --limit 1

# 5. Enable for scheduled execution
marvinctl platform tasks update <task-id> --enable
```

### Export/Import Tasks

```bash
# Export all tasks
marvinctl platform tasks list --output json > tasks.json

# Export single task
marvinctl platform tasks get my-task --output json > my-task.json

# Import/recreate task
marvinctl platform tasks create --file my-task.json
```

### Scripting with CLI

**Bash script to monitor task health:**

```bash
#!/bin/bash
# check-tasks.sh

# Get failed tasks
FAILED=$(marvinctl platform tasks list --failed-only --output json)
FAILED_COUNT=$(echo "$FAILED" | jq 'length')

if [ "$FAILED_COUNT" -gt 0 ]; then
  echo "⚠️ $FAILED_COUNT tasks failed!"
  echo "$FAILED" | jq -r '.[] | "\(.name) (last run: \(.last_run_at))"'

  # Send alert (example: Slack webhook)
  curl -X POST https://hooks.slack.com/services/YOUR/WEBHOOK/URL \
    -H 'Content-Type: application/json' \
    -d "{\"text\": \"$FAILED_COUNT scheduled tasks failed\"}"
fi
```

**Python script using CLI:**

```python
#!/usr/bin/env python3
import subprocess
import json

def get_tasks():
    result = subprocess.run(
        ['marvinctl', 'platform', 'tasks', 'list', '--output', 'json'],
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)

def check_task_health():
    tasks = get_tasks()

    for task in tasks:
        if task['enabled'] and task['last_status'] == 'failed':
            print(f"⚠️ Task '{task['name']}' is enabled but failing")

            # Get history
            history_result = subprocess.run(
                ['marvinctl', 'platform', 'tasks', 'history',
                 task['id'], '--limit', '5', '--output', 'json'],
                capture_output=True,
                text=True
            )
            history = json.loads(history_result.stdout)

            # Check if consistently failing
            recent_failures = [h for h in history if h['status'] == 'failed']
            if len(recent_failures) >= 3:
                print(f"   Consistently failing! Disabling task...")
                subprocess.run([
                    'marvinctl', 'platform', 'tasks', 'update',
                    task['id'], '--disable'
                ])

if __name__ == '__main__':
    check_task_health()
```

## Environment Variables

- `MARVIN_USER_TOKEN` - User authentication token
- `MARVIN_API_URL` - API base URL (default: from config)
- `MARVIN_WORKSPACE_ID` - Default workspace ID

## Troubleshooting

### "Authentication failed"
- Verify token: `echo $MARVIN_USER_TOKEN`
- Generate new token via web UI or API

### "Task type not found"
- Run `marvinctl platform tasks types` to see available types
- Check spelling and case sensitivity

### "Task not executing"
- Check if enabled: `marvinctl platform tasks get <id>`
- Verify schedule config is valid
- Check execution history for errors: `marvinctl platform tasks history <id>`

### "No output"
- Add `--output json` for debugging
- Check exit code: `echo $?`
- Verify workspace context

## Next Steps

- See [SDK Guide](./SDK-SCHEDULED-TASKS.md) for programmatic access
- See [API Reference](../src/marvin/routes/platform/scheduled_tasks_controller.py) for backend details
- See [TODO.md](../src/marvin/services/scheduled_tasks/TODO.md) for incomplete features
