---
name: cron
description: Schedule reminders and recurring tasks.
---

# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Two Modes

1. **Reminder** - message is sent directly to user
2. **Task** - message is a task description, agent executes and sends result

## Examples

Fixed reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

With timezone (for cron expressions):
```
cron(action="add", message="Good morning!", cron_expr="0 7 * * *", timezone="Asia/Ho_Chi_Minh")
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |

## Timezone Support

When using `cron_expr`, you can specify a timezone using the `timezone` parameter:
- If specified: Uses the given timezone (e.g., "Asia/Ho_Chi_Minh", "America/New_York")
- If not specified: Uses the system's local timezone

**Note:** The `every_seconds` mode doesn't need timezone as it's interval-based.
