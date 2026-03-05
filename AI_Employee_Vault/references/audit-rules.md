# Audit Rules — Silver Tier Reference

**Version:** 1.0.0
**Effective:** 2026-03-05

---

## Bottleneck Detection Thresholds

| Severity | Duration Multiplier | Description | Action |
|----------|-------------------|-------------|--------|
| Minor | 1.5x expected | Task slightly overdue | Note in briefing |
| Moderate | 2.0x expected | Task significantly delayed | Investigate cause |
| Critical | 3.0x+ expected | Task severely behind | Escalate to Admin |

### Calculation

```
delay_ratio = actual_duration / expected_duration

if delay_ratio >= 3.0:   severity = "Critical"
elif delay_ratio >= 2.0:  severity = "Moderate"
elif delay_ratio >= 1.5:  severity = "Minor"
else:                     severity = "On Track"
```

---

## Subscription Audit Thresholds

| Rule | Days Inactive | Action |
|------|---------------|--------|
| Active | 0-29 days | No action needed |
| Warning | 30-59 days | Flag in CEO Briefing |
| Critical | 60+ days | Recommend cancellation |
| Cost Alert | N/A | Flag services > $200/month |
| Renewal Alert | 14 days before | Include in briefing |

---

## Pipeline Health Rules

| Condition | Threshold | Severity | Action |
|-----------|-----------|----------|--------|
| Tasks stuck in Needs_Action | > 24 hours | Warning | Flag in Dashboard |
| Tasks stuck in Pending_Approval | > 48 hours | Escalation | Notify Admin |
| Consecutive rejections | 3+ for same task | Critical | Manual review required |
| Log write failure | Any | Critical | Halt pipeline |
| Empty Done folder | > 7 days | Warning | Investigate throughput |

---

## Approval Expiry Rules

| Field | Value | Description |
|-------|-------|-------------|
| Default TTL | 24 hours | Approval requests expire after this period |
| Stale Check | Every poll cycle | Watcher checks `expires` field in frontmatter |
| Expired Action | Move to Rejected | Auto-reject with `reason: expired` |

---

## Revenue Tracking Rules

| Metric | Calculation | Target |
|--------|-------------|--------|
| Weekly Revenue | Sum of `revenue` field in /Done/ tasks (last 7 days) | $2,500 |
| Monthly Revenue | Sum of `revenue` field in /Done/ tasks (current month) | $10,000 |
| Revenue Trend | This week vs. last week | Positive or stable |
| Completion Rate | Completed tasks / Total received (7 days) | > 90% |

---

## Log Retention Policy

| Log Type | Rotation | Retention | Location |
|----------|----------|-----------|----------|
| Daily JSON logs | Daily | 90 days minimum | `/Logs/YYYY-MM-DD.json` |
| Skill-specific logs | Per-skill | 30 days | `Skills/<name>/logs/` |
| Cron logs | Append | 90 days | `/Logs/cron-*.log` |
| CEO Briefings | Weekly | 1 year | `/Briefings/` |
