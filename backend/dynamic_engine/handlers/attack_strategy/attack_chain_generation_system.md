# Attack Chain Generation System

## Overview

- **Purpose**: Generate intelligent, objective-driven attack chains that sequence security testing tools into cohesive workflows. Integrates pattern selection, tool optimization, success probability calculation, and execution time estimation.
- **Category**: tooling
- **Severity**: critical
- **Tags**: attack-chain, generation, workflow, orchestration, objective-driven, pattern-based, success-probability

## Context and Use-Cases

The attack chain generation system is essential for:

- **Automated Attack Planning**: Generate sequences of tools automatically
- **Objective-Driven Workflows**: Tailor chains to specific goals
- **Success Probability Estimation**: Quantify chain success likelihood
- **Execution Time Planning**: Estimate total testing duration
- **Resource Allocation**: Plan tool execution order
- **Risk Assessment**: Inform testing strategy
- **Reporting**: Provide comprehensive attack plans
- **Reproducibility**: Enable consistent testing workflows

## Procedure / Knowledge Detail

### Attack Chain Generation Overview

**Input**: TargetProfile + Objective

**Output**: AttackChain with sequential steps

### Pattern-Based Attack Selection

The system uses predefined attack patterns for different target types and objectives.

#### WEB_APPLICATION Patterns

**Quick Mode**:
- Pattern: `vulnerability_assessment[:2]` (first 2 steps)
- Use case: Rapid vulnerability scanning
- Tools: nuclei, sqlmap (or similar)
- Duration: 15-20 minutes

**Comprehensive Mode** (default):
- Pattern: `web_reconnaissance` + `vulnerability_assessment`
- Use case: Full web application testing
- Tools: reconnaissance tools + vulnerability scanners
- Duration: 45-60 minutes

#### API_ENDPOINT Pattern

**Pattern**: `api_testing`
- Use case: API-specific testing
- Tools: arjun, nuclei, ffuf
- Duration: 30-40 minutes

#### NETWORK_HOST Patterns

**Comprehensive Mode**:
- Pattern: `comprehensive_network_pentest`
- Use case: Full network penetration testing
- Tools: nmap, autorecon, enum4linux-ng
- Duration: 60-90 minutes

**Quick Mode**:
- Pattern: `network_discovery`
- Use case: Network discovery only
- Tools: nmap, masscan
- Duration: 20-30 minutes

#### BINARY_FILE Patterns

**CTF Mode**:
- Pattern: `ctf_pwn_challenge`
- Use case: Capture-the-flag challenges
- Tools: ghidra, gdb, pwntools
- Duration: 30-60 minutes

**Default Mode**:
- Pattern: `binary_exploitation`
- Use case: Binary exploitation testing
- Tools: ghidra, radare2, angr
- Duration: 45-90 minutes

#### CLOUD_SERVICE Patterns

**AWS Mode**:
- Pattern: `aws_security_assessment`
- Tools: prowler, pacu
- Duration: 60-90 minutes

**Kubernetes Mode**:
- Pattern: `kubernetes_security_assessment`
- Tools: kube-hunter, kube-bench
- Duration: 30-45 minutes

**Containers Mode**:
- Pattern: `container_security_assessment`
- Tools: trivy, clair, docker-bench-security
- Duration: 30-45 minutes

**IaC Mode**:
- Pattern: `iac_security_assessment`
- Tools: checkov, terrascan
- Duration: 20-30 minutes

**Multi-Cloud Mode** (default):
- Pattern: `multi_cloud_assessment`
- Tools: scout-suite, cloudmapper
- Duration: 60-90 minutes

#### Bug Bounty Patterns

**Reconnaissance Mode**:
- Pattern: `bug_bounty_reconnaissance`
- Use case: Initial reconnaissance
- Duration: 30-45 minutes

**Vulnerability Hunting Mode**:
- Pattern: `bug_bounty_vulnerability_hunting`
- Use case: Active vulnerability discovery
- Duration: 60-120 minutes

**High Impact Mode**:
- Pattern: `bug_bounty_high_impact`
- Use case: Focus on high-impact vulnerabilities
- Duration: 45-90 minutes

### Attack Step Construction

For each step in the selected pattern:

#### 1. Tool Selection

**Source**: Step configuration from pattern

**Example**:
```python
step_config = {
    "tool": "nuclei",
    "parameters": {...}
}
```

#### 2. Parameter Optimization

**Method**: `optimize_parameters(tool, profile)`

**Purpose**: Tailor tool parameters to target

**Example**:
```python
optimized_params = self.optimize_parameters("nuclei", profile)
# Result: {"templates": "cves", "severity": "high", ...}
```

#### 3. Success Probability Calculation

**Formula**:
```
success_probability = tool_effectiveness × confidence_score
```

**Example**:
```python
effectiveness = 0.95  # nuclei for WEB_APPLICATION
confidence = 0.90    # high confidence in target analysis
success_prob = 0.95 × 0.90 = 0.855 (85.5%)
```

#### 4. Execution Time Estimation

**Mapping**: Tool-specific time estimates (in seconds)

**Examples**:
- nmap: 120 seconds
- gobuster: 300 seconds
- nuclei: 180 seconds
- sqlmap: 600 seconds
- ghidra: 300 seconds
- prowler: 600 seconds

#### 5. AttackStep Creation

**Structure**:
```python
step = AttackStep(
    tool="nuclei",
    parameters={"templates": "cves", "severity": "high"},
    expected_outcome="Discover vulnerabilities using nuclei",
    success_probability=0.855,
    execution_time_estimate=180
)
```

### Chain Metrics Calculation

#### Overall Success Probability

**Formula**:
```
chain_success = P(Step1) × P(Step2) × P(Step3) × ... × P(StepN)
```

**Example**:
```
Step 1: 0.85
Step 2: 0.80
Step 3: 0.75

Chain = 0.85 × 0.80 × 0.75 = 0.51 (51%)
```

#### Total Execution Time

**Calculation**: Sum of all step execution times

**Example**:
```
Step 1: 120 seconds
Step 2: 300 seconds
Step 3: 180 seconds

Total: 600 seconds (10 minutes)
```

#### Risk Level

**Source**: From target profile

**Example**:
```python
chain.risk_level = profile.risk_level  # "critical", "high", etc.
```

### Attack Chain Implementation

```python
def create_attack_chain(self, profile: TargetProfile, objective: str = "comprehensive") -> AttackChain:
    # Create empty chain
    chain = AttackChain(profile)

    # Select pattern based on target type and objective
    if profile.target_type == TargetType.WEB_APPLICATION:
        if objective == "quick":
            pattern = self.attack_patterns["vulnerability_assessment"][:2]
        else:
            pattern = self.attack_patterns["web_reconnaissance"] + \
                     self.attack_patterns["vulnerability_assessment"]
    elif profile.target_type == TargetType.API_ENDPOINT:
        pattern = self.attack_patterns["api_testing"]
    elif profile.target_type == TargetType.NETWORK_HOST:
        if objective == "comprehensive":
            pattern = self.attack_patterns["comprehensive_network_pentest"]
        else:
            pattern = self.attack_patterns["network_discovery"]
    elif profile.target_type == TargetType.BINARY_FILE:
        if objective == "ctf":
            pattern = self.attack_patterns["ctf_pwn_challenge"]
        else:
            pattern = self.attack_patterns["binary_exploitation"]
    elif profile.target_type == TargetType.CLOUD_SERVICE:
        if objective == "aws":
            pattern = self.attack_patterns["aws_security_assessment"]
        elif objective == "kubernetes":
            pattern = self.attack_patterns["kubernetes_security_assessment"]
        elif objective == "containers":
            pattern = self.attack_patterns["container_security_assessment"]
        elif objective == "iac":
            pattern = self.attack_patterns["iac_security_assessment"]
        else:
            pattern = self.attack_patterns["multi_cloud_assessment"]
    else:
        if objective == "bug_bounty_recon":
            pattern = self.attack_patterns["bug_bounty_reconnaissance"]
        elif objective == "bug_bounty_hunting":
            pattern = self.attack_patterns["bug_bounty_vulnerability_hunting"]
        elif objective == "bug_bounty_high_impact":
            pattern = self.attack_patterns["bug_bounty_high_impact"]
        else:
            pattern = self.attack_patterns["web_reconnaissance"]

    # Create attack steps
    for step_config in pattern:
        tool = step_config["tool"]
        optimized_params = self.optimize_parameters(tool, profile)

        # Calculate success probability
        effectiveness = self.tool_effectiveness.get(profile.target_type.value, {}).get(tool, 0.5)
        success_prob = effectiveness * profile.confidence_score

        # Estimate execution time
        time_estimates = {
            "nmap": 120, "gobuster": 300, "nuclei": 180, "nikto": 240,
            "sqlmap": 600, "ffuf": 200, "hydra": 900, "amass": 300,
            "ghidra": 300, "radare2": 180, "gdb": 120, "gdb-peda": 150,
            "angr": 600, "pwntools": 240, "ropper": 120, "one-gadget": 60,
            "checksec": 30, "pwninit": 60, "libc-database": 90,
            "prowler": 600, "scout-suite": 480, "cloudmapper": 300, "pacu": 420,
            "trivy": 180, "clair": 240, "kube-hunter": 300, "kube-bench": 120,
            "docker-bench-security": 180, "falco": 120, "checkov": 240, "terrascan": 200
        }
        exec_time = time_estimates.get(tool, 180)

        # Create step
        step = AttackStep(
            tool=tool,
            parameters=optimized_params,
            expected_outcome=f"Discover vulnerabilities using {tool}",
            success_probability=success_prob,
            execution_time_estimate=exec_time
        )

        chain.add_step(step)

    # Calculate overall chain metrics
    chain.calculate_success_probability()
    chain.risk_level = profile.risk_level

    return chain
```

## Practical Examples

### Example 1: Quick Web Application Attack Chain

**Input**:
```python
profile = TargetProfile(
    target_type=TargetType.WEB_APPLICATION,
    confidence_score=0.90,
    risk_level="high"
)
objective = "quick"
```

**Chain Generation**:

```text
Step 1: Pattern Selection
├─ Target type: WEB_APPLICATION
├─ Objective: quick
└─ Pattern: vulnerability_assessment[:2]

Step 2: Create Attack Steps
├─ Step 1: nuclei
│  ├─ Effectiveness: 0.95
│  ├─ Success Prob: 0.95 × 0.90 = 0.855
│  └─ Exec Time: 180s
├─ Step 2: sqlmap
│  ├─ Effectiveness: 0.90
│  ├─ Success Prob: 0.90 × 0.90 = 0.81
│  └─ Exec Time: 600s

Step 3: Calculate Chain Metrics
├─ Chain Success: 0.855 × 0.81 = 0.692 (69.2%)
├─ Total Time: 780s (13 minutes)
└─ Risk Level: high
```

**Output Chain**:
```python
AttackChain(
    steps=[
        AttackStep(tool="nuclei", success_probability=0.855, execution_time_estimate=180),
        AttackStep(tool="sqlmap", success_probability=0.81, execution_time_estimate=600)
    ],
    success_probability=0.692,
    estimated_time=780,
    risk_level="high"
)
```

### Example 2: Comprehensive Network Host Attack Chain

**Input**:
```python
profile = TargetProfile(
    target_type=TargetType.NETWORK_HOST,
    confidence_score=0.85,
    risk_level="critical"
)
objective = "comprehensive"
```

**Chain Generation**:

```text
Step 1: Pattern Selection
├─ Target type: NETWORK_HOST
├─ Objective: comprehensive
└─ Pattern: comprehensive_network_pentest

Step 2: Create Attack Steps
├─ Step 1: nmap
│  ├─ Success Prob: 0.95 × 0.85 = 0.8075
│  └─ Exec Time: 120s
├─ Step 2: autorecon
│  ├─ Success Prob: 0.95 × 0.85 = 0.8075
│  └─ Exec Time: 300s
├─ Step 3: enum4linux-ng
│  ├─ Success Prob: 0.88 × 0.85 = 0.748
│  └─ Exec Time: 240s

Step 3: Calculate Chain Metrics
├─ Chain Success: 0.8075 × 0.8075 × 0.748 = 0.486 (48.6%)
├─ Total Time: 660s (11 minutes)
└─ Risk Level: critical
```

### Example 3: AWS Cloud Security Assessment

**Input**:
```python
profile = TargetProfile(
    target_type=TargetType.CLOUD_SERVICE,
    confidence_score=0.80,
    risk_level="high"
)
objective = "aws"
```

**Chain Generation**:

```text
Step 1: Pattern Selection
├─ Target type: CLOUD_SERVICE
├─ Objective: aws
└─ Pattern: aws_security_assessment

Step 2: Create Attack Steps
├─ Step 1: prowler
│  ├─ Success Prob: 0.95 × 0.80 = 0.76
│  └─ Exec Time: 600s
├─ Step 2: pacu
│  ├─ Success Prob: 0.90 × 0.80 = 0.72
│  └─ Exec Time: 420s

Step 3: Calculate Chain Metrics
├─ Chain Success: 0.76 × 0.72 = 0.547 (54.7%)
├─ Total Time: 1020s (17 minutes)
└─ Risk Level: high
```

### Example 4: Binary Exploitation Attack Chain

**Input**:
```python
profile = TargetProfile(
    target_type=TargetType.BINARY_FILE,
    confidence_score=0.75,
    risk_level="medium"
)
objective = "ctf"
```

**Chain Generation**:

```text
Step 1: Pattern Selection
├─ Target type: BINARY_FILE
├─ Objective: ctf
└─ Pattern: ctf_pwn_challenge

Step 2: Create Attack Steps
├─ Step 1: ghidra
│  ├─ Success Prob: 0.95 × 0.75 = 0.7125
│  └─ Exec Time: 300s
├─ Step 2: gdb-peda
│  ├─ Success Prob: 0.90 × 0.75 = 0.675
│  └─ Exec Time: 150s
├─ Step 3: pwntools
│  ├─ Success Prob: 0.88 × 0.75 = 0.66
│  └─ Exec Time: 240s

Step 3: Calculate Chain Metrics
├─ Chain Success: 0.7125 × 0.675 × 0.66 = 0.316 (31.6%)
├─ Total Time: 690s (11.5 minutes)
└─ Risk Level: medium
```

## Attack Pattern Characteristics

### Pattern Complexity

| Target Type | Quick | Comprehensive | Tools | Duration |
|---|---|---|---|---|
| WEB_APPLICATION | 2 steps | 5-7 steps | 5-7 | 15-60 min |
| NETWORK_HOST | 2 steps | 3-4 steps | 3-4 | 20-90 min |
| API_ENDPOINT | - | 3-4 steps | 3-4 | 30-40 min |
| BINARY_FILE | - | 3-4 steps | 3-4 | 30-90 min |
| CLOUD_SERVICE | - | 2-3 steps | 2-3 | 20-90 min |

### Success Probability Impact

**Chain Length Effect**:

| Steps | Base Prob | 0.85 Conf | 0.75 Conf | 0.65 Conf |
|---|---|---|---|---|
| 2 | 0.90 | 0.72 | 0.57 | 0.43 |
| 3 | 0.85 | 0.61 | 0.43 | 0.28 |
| 4 | 0.80 | 0.52 | 0.32 | 0.18 |
| 5 | 0.75 | 0.42 | 0.24 | 0.12 |

## Related Knowledge Items

- **target_analysis_workflow**: Provides target profile
- **tool_selection_strategy**: Selects tools for chain
- **success_probability_framework**: Calculates probabilities
- **confidence_scoring_system**: Influences success probability
- **parameter_optimization_system**: Optimizes tool parameters

## Best Practices

1. **Match Objective to Goal**: Choose objective aligned with testing goals
2. **Verify Target Profile**: Ensure complete target analysis before chain generation
3. **Monitor Confidence**: Track confidence score impact on probabilities
4. **Plan Execution Time**: Consider total duration for scheduling
5. **Validate Patterns**: Ensure patterns are appropriate for target type
6. **Document Chain**: Record chain for reproducibility
7. **Adjust Parameters**: Customize tool parameters for target
8. **Track Results**: Monitor actual vs. predicted success rates

## Limitations and Considerations

### Current Limitations

- **Static Patterns**: Doesn't adapt to specific conditions
- **Fixed Time Estimates**: Doesn't account for network conditions
- **No Dependency Modeling**: Assumes steps are independent
- **Limited Objective Support**: Only predefined objectives supported
- **No Failure Handling**: Doesn't adjust chain on step failure
- **No Tool Availability Check**: Assumes all tools are installed
- **No Resource Constraints**: Doesn't consider available resources

### Improvement Opportunities

1. **Dynamic Patterns**: Adjust based on target characteristics
2. **Adaptive Time Estimation**: Consider network conditions
3. **Dependency Modeling**: Model step dependencies
4. **Custom Objectives**: Support user-defined objectives
5. **Failure Handling**: Adjust chain on step failure
6. **Tool Availability**: Check tool installation
7. **Resource Constraints**: Consider available resources
8. **Machine Learning**: Train models for better patterns

## Performance Metrics

| Metric | Value |
|--------|-------|
| Chain Generation Latency | <10ms |
| Average Chain Length | 3-4 steps |
| Average Chain Duration | 20-60 minutes |
| Success Probability Range | 0.3-0.9 |

## Notes

- Attack chains are objective-driven
- Success probability decreases with chain length
- Execution time is sum of step times
- Patterns are predefined for consistency
- Confidence score significantly impacts success probability
- Risk level guides testing intensity

## Integration Points

**Called By**:

- Attack planning phase
- Strategy selection
- Penetration testing workflows
- Automated testing pipelines

**Calls**:

- `optimize_parameters()` - Parameter optimization
- `calculate_success_probability()` - Probability calculation
- Tool effectiveness lookup
- Time estimation lookup

**Data Flow**:

```text
create_attack_chain(profile, objective)
    ├─ Select pattern by target type + objective
    ├─ For each step in pattern:
    │  ├─ Get tool from step config
    │  ├─ Optimize parameters
    │  ├─ Calculate success probability
    │  ├─ Estimate execution time
    │  └─ Create AttackStep
    ├─ Calculate chain success probability
    ├─ Set risk level
    └─ Return AttackChain
```

## Future Enhancements

1. **Dynamic Patterns**: Adjust based on conditions
2. **Adaptive Time Estimation**: Consider network conditions
3. **Dependency Modeling**: Model step dependencies
4. **Custom Objectives**: Support user-defined objectives
5. **Failure Handling**: Adjust chain on failure
6. **Tool Availability**: Check installation
7. **Resource Constraints**: Consider resources
8. **Machine Learning**: Train models for patterns
