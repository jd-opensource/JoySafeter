# SQLMap Parameter Optimization

## Overview

- **Purpose**: Intelligently optimize SQLMap SQL injection testing parameters based on detected database types and aggressiveness context
- **Category**: tool-optimization
- **Severity**: high
- **Tags**: sqlmap, parameter-optimization, sql-injection, database-specific

## Procedure / Knowledge Detail

### Database Type Detection

**PHP Detection**: MySQL
- Parameter: `--dbms=mysql --batch`

**ASP.NET Detection**: MSSQL
- Parameter: `--dbms=mssql --batch`

**Default**: No specific database
- Parameter: `--batch`

### Aggressiveness Adjustment

**Aggressive Mode**:
- Parameters: `--level=3 --risk=2`
- Coverage: Comprehensive testing

**Conservative Mode** (default):
- No additional parameters
- Coverage: Basic testing

### Implementation Code

```python
def _optimize_sqlmap_params(self, profile: TargetProfile, context: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize SQLMap parameters"""
    params = {"url": profile.target}

    if TechnologyStack.PHP in profile.technologies:
        params["additional_args"] = "--dbms=mysql --batch"
    elif TechnologyStack.DOTNET in profile.technologies:
        params["additional_args"] = "--dbms=mssql --batch"
    else:
        params["additional_args"] = "--batch"

    if context.get("aggressive", False):
        params["additional_args"] += " --level=3 --risk=2"

    return params
```

## Related Knowledge Items

- **technology_detection_heuristics**: Detects database types
- **tool_selection_strategy**: Selects sqlmap
- **attack_chain_generation_system**: Uses optimized parameters

## Best Practices

1. Use `--batch` for automated testing
2. Specify `--dbms` when known
3. Use `--level` 1-5 (default 1)
4. Use `--risk` 1-3 (default 1)
5. Use `--technique` for specific injection types
6. Save results with `-o` flag

## Notes

- Injection techniques: B (Boolean), E (Error), U (Union), S (Stacked), T (Time-based)
- Database types: MySQL, MSSQL, PostgreSQL, Oracle, SQLite
- Common parameters: `--dbs`, `--tables`, `--dump`
