# Scheduled Tasks SDK Guide

The Marvin SDK provides full TypeScript support for managing scheduled tasks. The SDK auto-generates from the OpenAPI spec, so all endpoints are typed and available immediately.

## Installation

```bash
npm install marvin-sdk
# or
yarn add marvin-sdk
```

## Quick Start

```typescript
import { MarvinClient } from 'marvin-sdk';

const marvin = new MarvinClient({
  baseUrl: 'https://api.marvin.example.com',
  apiKey: 'your-api-key-here'
});

// Create a scheduled task
const task = await marvin.platform.scheduledTasks.create({
  name: 'Daily Cleanup',
  description: 'Clean up old temp files every day',
  task_type: 'cleanup_temp_files',
  schedule_type: 'interval',
  schedule_config: {
    interval_seconds: 86400  // 24 hours
  },
  task_config: {
    age_hours: 24,
    dry_run: false
  },
  enabled: true
});

console.log(`Task created: ${task.id}`);
```

## API Reference

### List All Tasks

```typescript
const tasks = await marvin.platform.scheduledTasks.list();

tasks.forEach(task => {
  console.log(`${task.name} - Next run: ${task.next_run_at}`);
});
```

### Get Task by ID or Slug

```typescript
// By ID
const task = await marvin.platform.scheduledTasks.get('task-uuid');

// By slug
const task = await marvin.platform.scheduledTasks.get('daily-cleanup');
```

### Create Task

```typescript
// Interval-based (every N seconds)
const intervalTask = await marvin.platform.scheduledTasks.create({
  name: 'Hourly Report',
  task_type: 'generate_report',
  schedule_type: 'interval',
  schedule_config: { interval_seconds: 3600 },
  enabled: true
});

// Cron-based
const cronTask = await marvin.platform.scheduledTasks.create({
  name: 'Daily Backup',
  task_type: 'backup_database',
  schedule_type: 'cron',
  schedule_config: {
    cron_expression: '0 2 * * *',  // 2 AM every day
    timezone: 'America/New_York'
  },
  enabled: true
});

// One-time execution
const onceTask = await marvin.platform.scheduledTasks.create({
  name: 'Launch Day Publish',
  task_type: 'publish_scheduled_entries',
  schedule_type: 'once',
  schedule_config: {
    run_at: '2026-12-25T00:00:00Z'
  },
  enabled: true
});
```

### Update Task

```typescript
const updated = await marvin.platform.scheduledTasks.update('task-id', {
  enabled: false,  // Disable the task
  description: 'Updated description',
  schedule_config: { interval_seconds: 7200 }  // Change to every 2 hours
});
```

### Delete Task

```typescript
await marvin.platform.scheduledTasks.delete('task-id');
```

### Manually Trigger Task

```typescript
// Execute task immediately, bypassing the schedule
await marvin.platform.scheduledTasks.execute('task-id');

console.log('Task triggered! Check execution history for results.');
```

### View Execution History

```typescript
const history = await marvin.platform.scheduledTasks.history('task-id', {
  limit: 50
});

history.forEach(exec => {
  console.log(`${exec.executed_at} - ${exec.status} (${exec.duration_ms}ms)`);
  if (exec.error_message) {
    console.error(`  Error: ${exec.error_message}`);
  }
});
```

### Discover Available Task Types

```typescript
// Simple list
const types = await marvin.platform.scheduledTasks.taskTypes();
console.log(types);  // ['cleanup_temp_files', 'publish_scheduled_entries', ...]

// Detailed metadata with config schemas
const typesDetailed = await marvin.platform.scheduledTasks.taskTypes({ detailed: true });

typesDetailed.forEach(type => {
  console.log(`${type.name} (${type.task_type})`);
  console.log(`  Description: ${type.description}`);
  if (type.config_schema) {
    console.log(`  Config:`, type.config_schema);
  }
});
```

## Common Patterns

### Monitor Task Health

```typescript
async function checkTaskHealth(taskId: string) {
  const task = await marvin.platform.scheduledTasks.get(taskId);

  if (!task.enabled) {
    console.log('⚠️ Task is disabled');
    return;
  }

  if (task.failure_count > 5) {
    console.log(`🚨 Task has failed ${task.failure_count} times consecutively!`);

    // Get recent failures
    const history = await marvin.platform.scheduledTasks.history(taskId, { limit: 5 });
    const failures = history.filter(h => h.status === 'failed');

    failures.forEach(f => console.error(`  - ${f.error_message}`));
  } else {
    console.log(`✓ Task healthy (${task.failure_count} failures)`);
  }
}
```

### Create Task with Validation

```typescript
async function createValidatedTask(taskData: any) {
  // Get available types
  const types = await marvin.platform.scheduledTasks.taskTypes({ detailed: true });
  const type = types.find(t => t.task_type === taskData.task_type);

  if (!type) {
    throw new Error(`Unknown task type: ${taskData.task_type}`);
  }

  console.log(`Creating task: ${type.name}`);
  console.log(`Description: ${type.description}`);

  // Validate config against schema if available
  if (type.config_schema && taskData.task_config) {
    // Use a JSON schema validator here
    console.log('Validating task_config against schema...');
  }

  return await marvin.platform.scheduledTasks.create(taskData);
}
```

### Batch Operations

```typescript
// Disable all failed tasks
async function disableFailedTasks() {
  const tasks = await marvin.platform.scheduledTasks.list();
  const failed = tasks.filter(t => t.last_status === 'failed' && t.failure_count > 3);

  console.log(`Disabling ${failed.length} failed tasks...`);

  await Promise.all(
    failed.map(task =>
      marvin.platform.scheduledTasks.update(task.id, { enabled: false })
    )
  );
}

// Get execution stats
async function getExecutionStats() {
  const tasks = await marvin.platform.scheduledTasks.list();

  const stats = {
    total: tasks.length,
    enabled: tasks.filter(t => t.enabled).length,
    disabled: tasks.filter(t => !t.enabled).length,
    neverRun: tasks.filter(t => !t.last_run_at).length,
    failed: tasks.filter(t => t.last_status === 'failed').length,
    success: tasks.filter(t => t.last_status === 'success').length
  };

  return stats;
}
```

## TypeScript Types

The SDK auto-generates types from the OpenAPI spec:

```typescript
import type {
  ScheduledTaskCreate,
  ScheduledTaskUpdate,
  ScheduledTaskRead,
  ScheduledTaskExecutionLogRead
} from 'marvin-sdk';

// All fields are typed
const taskData: ScheduledTaskCreate = {
  name: 'My Task',
  task_type: 'cleanup_temp_files',
  schedule_type: 'interval',  // Type: 'cron' | 'interval' | 'once'
  schedule_config: {},
  enabled: true
};
```

## Error Handling

```typescript
try {
  const task = await marvin.platform.scheduledTasks.create(taskData);
  console.log('Success:', task.id);
} catch (error) {
  if (error.status === 404) {
    console.error('Task type not found');
  } else if (error.status === 400) {
    console.error('Invalid request:', error.body);
  } else {
    console.error('Unexpected error:', error);
  }
}
```

## Regenerating the SDK

When the API changes (new endpoints, fields, etc.):

```bash
# In marvin backend repo
npm run generate:sdk

# Or manually
cd ../marvin-sdk
npx openapi-generator-cli generate \
  -i http://localhost:8000/openapi.json \
  -g typescript-fetch \
  -o ./src/generated
```

## Next Steps

- See [CLI Guide](./CLI-SCHEDULED-TASKS.md) for command-line usage
- See [API Reference](../src/marvin/routes/platform/scheduled_tasks_controller.py) for backend implementation
- See [TODO.md](../src/marvin/services/scheduled_tasks/TODO.md) for incomplete features
