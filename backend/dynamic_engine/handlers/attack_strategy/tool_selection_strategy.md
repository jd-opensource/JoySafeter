# Tool Selection Strategy

## Overview

- **Purpose**: Select optimal security testing tools based on target profile and operational objectives. Enables data-driven tool selection with multiple strategies (quick, comprehensive, stealth) and technology-specific augmentation.
- **Category**: tooling
- **Severity**: high
- **Tags**: tool-selection, strategy, optimization, objective-driven, effectiveness-ranking, technology-specific

## Context and Use-Cases

The tool selection strategy is essential for:

- **Objective-Driven Selection**: Choose tools based on operational goals
- **Effectiveness Optimization**: Select highest-effectiveness tools for target type
- **Resource Efficiency**: Balance tool count with effectiveness
- **Stealth Operations**: Select passive tools for low-detection scenarios
- **Technology-Specific Testing**: Add specialized tools for detected technologies
- **Attack Planning**: Inform attack chain construction
- **Time Optimization**: Quick mode for rapid assessment
- **Comprehensive Coverage**: Full mode for thorough testing

## Procedure / Knowledge Detail

### Selection Strategy Overview

**Input**: TargetProfile + Objective

**Output**: List of selected tools

### Three Objective-Based Selection Modes

#### Mode 1: Quick Selection

**Objective**: `"quick"`

**Strategy**: Select top 3 most effective tools

**Logic**:
- Get all tools for target type
- Sort by effectiveness (descending)
- Select top 3
- Add technology-specific tools

**Use Case**: Rapid reconnaissance, time-constrained testing

**Example**:

```python
objective = "quick"
target_type = WEB_APPLICATION

# All tools: [nuclei, gobuster, sqlmap, nikto, ffuf]
# Effectiveness: {nuclei: 0.95, gobuster: 0.90, sqlmap: 0.90, nikto: 0.85, ffuf: 0.88}

# Sorted: [nuclei (0.95), gobuster (0.90), sqlmap (0.90), ffuf (0.88), nikto (0.85)]
# Top 3: [nuclei, gobuster, sqlmap]

selected_tools = ["nuclei", "gobuster", "sqlmap"]
```

#### Mode 2: Comprehensive Selection

**Objective**: `"comprehensive"` (default)

**Strategy**: Select all tools with effectiveness > 0.7

**Logic**:
- Get all tools for target type
- Filter by effectiveness threshold (0.7)
- Include all qualifying tools
- Add technology-specific tools

**Use Case**: Thorough testing, complete coverage

**Example**:

```python
objective = "comprehensive"
target_type = WEB_APPLICATION

# All tools: [nuclei, gobuster, sqlmap, nikto, ffuf]
# Effectiveness: {nuclei: 0.95, gobuster: 0.90, sqlmap: 0.90, nikto: 0.85, ffuf: 0.88}

# Filter (> 0.7): [nuclei (0.95), gobuster (0.90), sqlmap (0.90), nikto (0.85), ffuf (0.88)]
# All pass threshold

selected_tools = ["nuclei", "gobuster", "sqlmap", "nikto", "ffuf"]
```

#### Mode 3: Stealth Selection

**Objective**: `"stealth"`

**Strategy**: Select passive tools with lower detection probability

**Logic**:
- Define passive tool list
- Filter base tools by stealth list
- Include only passive tools
- Add technology-specific tools

**Passive Tools**: `["amass", "subfinder", "httpx", "nuclei"]`

**Use Case**: Covert reconnaissance, evasion-focused testing

**Example**:

```python
objective = "stealth"
target_type = WEB_APPLICATION

# Base tools: [nuclei, gobuster, sqlmap, nikto, ffuf]
# Stealth list: [amass, subfinder, httpx, nuclei]

# Intersection: [nuclei]

selected_tools = ["nuclei"]
```

#### Mode 4: Default Selection

**Objective**: Any other value

**Strategy**: Select all available tools

**Logic**:
- Return all tools for target type
- Add technology-specific tools

**Use Case**: Fallback, exploratory testing

### Technology-Specific Tool Augmentation

**Purpose**: Add specialized tools for detected technologies

**Logic**:
- Iterate through detected technologies
- Check for technology-specific tools
- Add if not already selected
- Prevent duplicates

**Technology Mappings**:

| Technology | Specialized Tool | Rationale |
|---|---|---|
| WORDPRESS | wpscan | WordPress-specific vulnerability scanner |
| PHP | nikto | Web server scanner (PHP detection) |

**Example**:

```python
profile.technologies = [TechnologyStack.WORDPRESS, TechnologyStack.PHP]
selected_tools = ["nuclei", "gobuster"]

# Add WordPress-specific tool
if WORDPRESS in technologies and "wpscan" not in selected_tools:
    selected_tools.append("wpscan")

# Add PHP-specific tool
if PHP in technologies and "nikto" not in selected_tools:
    selected_tools.append("nikto")

# Result: ["nuclei", "gobuster", "wpscan", "nikto"]
```

## Notes

- Tool selection is objective-driven
- Effectiveness ranking ensures quality
- Technology-specific tools enhance coverage
- Stealth mode minimizes detection
- Quick mode balances speed and coverage
- Comprehensive mode maximizes coverage

## Integration Points

**Called By**:

- Attack chain generation
- Strategy selection
- Reconnaissance planning
- Tool orchestration

**Calls**:

- Tool effectiveness lookup
- Target type comparison
- Technology detection check

**Data Flow**:

```text
select_optimal_tools(profile, objective)
    ├─ Get target type
    ├─ Lookup effectiveness map
    ├─ Get base tools
    ├─ Apply objective filtering
    │   ├─ Quick: Top 3
    │   ├─ Comprehensive: >0.7
    │   ├─ Stealth: Passive only
    │   └─ Default: All
    ├─ Add technology-specific tools
    └─ Return selected tools
```
