# Success Probability Framework

## Overview

- **Purpose**: Quantify the likelihood of attack chain success through probabilistic analysis. Enables data-driven strategy optimization and resource allocation.
- **Category**: tooling
- **Severity**: high
- **Tags**: success-probability, attack-chain, tool-effectiveness, confidence-scoring, probabilistic-analysis, decision-engine, optimization

## Context and Use-Cases

The success probability framework is essential for:

- **Attack Strategy Optimization**: Prioritize high-probability attack paths
- **Resource Allocation**: Allocate resources to most promising strategies
- **Risk Assessment**: Quantify likelihood of successful exploitation
- **Tool Selection**: Choose tools with highest success likelihood
- **Chain Composition**: Build attack chains with optimal success rates
- **Reporting**: Communicate attack feasibility to stakeholders
- **Contingency Planning**: Prepare fallback strategies for low-probability paths
- **Performance Metrics**: Track actual vs. predicted success rates

## Procedure / Knowledge Detail

### Two-Level Probability System

The framework operates at two levels:

#### Level 1: Individual Step Success Probability

**Formula**:

```text
Step Success Probability = Tool Effectiveness × Target Confidence Score
```

**Components**:

1. **Tool Effectiveness** (0.0 - 1.0)
   - Measures how well a tool performs against a specific target type
   - Based on tool characteristics and target type
   - Pre-calculated effectiveness scores per tool/target combination
   - Example: nmap against NETWORK_HOST = 0.95

2. **Target Confidence Score** (0.0 - 1.0)
   - Measures confidence in target analysis accuracy
   - Reflects reliability of reconnaissance data
   - Influenced by:
     - Quantity of gathered information
     - Quality of target characterization
     - Certainty of technology detection
   - Higher confidence = more reliable probability estimate

**Calculation Example**:

```text
Tool: nmap
Target Type: NETWORK_HOST
Tool Effectiveness: 0.95
Target Confidence: 0.85

Step Success Probability = 0.95 × 0.85 = 0.8075 (80.75%)
```

#### Level 2: Overall Chain Success Probability

**Formula**:

```text
Chain Success Probability = P(Step1) × P(Step2) × P(Step3) × ... × P(StepN)
```

**Rationale**:

- Sequential steps are dependent
- Each step must succeed for chain to succeed
- Compound probability decreases with more steps
- Reflects realistic attack complexity

**Calculation Example**:

```text
Step 1 (Reconnaissance): 0.95
Step 2 (Enumeration): 0.85
Step 3 (Vulnerability Scanning): 0.90
Step 4 (Exploitation): 0.75

Chain Success Probability = 0.95 × 0.85 × 0.90 × 0.75 = 0.5746 (57.46%)
```
