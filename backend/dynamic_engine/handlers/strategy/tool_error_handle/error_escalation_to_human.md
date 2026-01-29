# Error Escalation to Human

## Overview

- Purpose: Escalate complex errors to human operators with full context for manual resolution
- Category: incident_response
- Severity: high
- Tags: escalation, human-intervention, incident-response

## Context and Use-Cases

- Permission denied errors requiring privilege escalation
- Authentication failures requiring credentials
- Tool installation requirements
- Unknown errors beyond automated recovery
- Critical failures requiring immediate attention

## Procedure / Knowledge detail

### Escalation Strategy

```
Action: ESCALATE_TO_HUMAN
Parameters:
  - message: Human-readable error description
  - urgency: low|medium|high
Max Attempts: 1
Success Probability: 0.9
Estimated Time: 300 seconds (5 minutes)
```

### Escalation Urgency Levels

**Low Urgency**
- Tool installation required
- Non-critical operation failure
- Can be deferred to maintenance window

**Medium Urgency**
- Unknown errors
- Unexpected failures
- Requires investigation

**High Urgency**
- Authentication failures
- Permission denied errors
- Critical operation failure

### Escalation Data Structure

```python
escalation_data = {
    "timestamp": "2024-01-01T12:00:00Z",
    "tool": "nmap",
    "target": "192.168.1.1",
    "error_type": "permission_denied",
    "error_message": "sudo required",
    "attempt_count": 1,
    "urgency": "medium",
    "suggested_actions": [
        "Run the command with sudo privileges",
        "Check file/directory permissions",
        "Verify user is in required groups"
    ],
    "context": {
        "parameters": {"ports": "1-65535"},
        "system_resources": {
            "cpu_percent": 45.2,
            "memory_percent": 62.1,
            "disk_percent": 78.5
        },
        "recent_errors": ["timeout", "permission_denied"]
    }
}
```

### Human Suggestions by Error Type

#### Permission Denied

```
- Run the command with sudo privileges
- Check file/directory permissions
- Verify user is in required groups
```

#### Tool Not Found

```
- Install {tool_name} using package manager
- Check if tool is in PATH
- Verify tool installation
```

#### Network Unreachable

```
- Check network connectivity
- Verify target is accessible
- Check firewall rules
```

#### Rate Limited

```
- Wait before retrying
- Use slower scan rates
- Check API rate limits
```

#### Unknown Error

```
- Review error details and logs
```

## Examples

### Escalation Example

```python
from error_handler_error_handler import IntelligentErrorHandler, ErrorType, ErrorContext
from datetime import datetime

handler = IntelligentErrorHandler()

# Create error context for permission denied
error_context = ErrorContext(
    tool_name="nmap",
    target="192.168.1.1",
    parameters={"ports": "1-65535"},
    error_type=ErrorType.PERMISSION_DENIED,
    error_message="sudo required",
    attempt_count=1,
    timestamp=datetime.now(),
    stack_trace="...",
    system_resources=handler._get_system_resources()
)

# Escalate to human
escalation_data = handler.escalate_to_human(
    error_context,
    urgency="medium"
)

print(f"Escalation ID: {escalation_data['timestamp']}")
print(f"Tool: {escalation_data['tool']}")
print(f"Urgency: {escalation_data['urgency']}")
print(f"Suggested Actions:")
for action in escalation_data['suggested_actions']:
    print(f"  - {action}")
```

### Escalation with Full Context

```python
import json
from error_handler_error_handler import IntelligentErrorHandler

handler = IntelligentErrorHandler()

# Get error statistics
error_stats = handler.get_error_statistics()

# Check if escalation is needed
if error_stats['total_errors'] > 10:
    print("Multiple errors detected, escalating to human")

    escalation_data = {
        "timestamp": datetime.now().isoformat(),
        "error_summary": error_stats,
        "message": "Multiple errors detected in tool execution",
        "urgency": "high"
    }

    # Log escalation
    print(json.dumps(escalation_data, indent=2))
```

### Escalation Notification

```python
def send_escalation_notification(escalation_data):
    """Send escalation notification to human operators"""

    message = f"""
    ERROR ESCALATION REQUIRED

    Tool: {escalation_data['tool']}
    Target: {escalation_data['target']}
    Error Type: {escalation_data['error_type']}
    Urgency: {escalation_data['urgency']}

    Error Message:
    {escalation_data['error_message']}

    Suggested Actions:
    """

    for i, action in enumerate(escalation_data['suggested_actions'], 1):
        message += f"\n    {i}. {action}"

    message += f"\n\nContext:\n{json.dumps(escalation_data['context'], indent=2)}"

    # Send notification (email, Slack, PagerDuty, etc.)
    # notify_operators(message)

    return message
```

### Escalation History

```python
def get_escalation_history(handler):
    """Get history of escalated errors"""

    escalations = []

    for error in handler.error_history:
        # Check if error was escalated
        if error.error_type in [
            ErrorType.PERMISSION_DENIED,
            ErrorType.AUTHENTICATION_FAILED,
            ErrorType.TOOL_NOT_FOUND,
            ErrorType.UNKNOWN
        ]:
            escalations.append({
                "timestamp": error.timestamp.isoformat(),
                "tool": error.tool_name,
                "target": error.target,
                "error_type": error.error_type.value,
                "error_message": error.error_message
            })

    return escalations
```

## Best Practices

- **Provide context** - Include all relevant information for investigation
- **Suggest actions** - Offer specific remediation steps
- **Set urgency** - Clearly indicate priority level
- **Log escalations** - Track all escalations for analysis
- **Notify promptly** - Alert operators immediately
- **Track resolution** - Monitor escalation resolution time

## Related Knowledge Items

- **error_classification_patterns** - Error type detection
- **timeout_error_recovery** - Timeout handling
- **graceful_degradation** - Degradation strategies
