# Target Analysis Workflow

## Overview

- **Purpose**: Orchestrate comprehensive target analysis through a unified pipeline. Integrates all analysis methods to create a complete target profile with type classification, network information, technology detection, attack surface scoring, risk assessment, and confidence metrics.
- **Category**: tooling
- **Severity**: high
- **Tags**: target-analysis, workflow, orchestration, profile-generation, reconnaissance, decision-engine

## Context and Use-Cases

The target analysis workflow is essential for:

- **Initial Reconnaissance**: Comprehensive target profiling from minimal input
- **Profile Generation**: Create complete TargetProfile with all metrics
- **Attack Planning**: Inform tool selection and strategy decisions
- **Risk Assessment**: Quantify target risk and prioritization
- **Confidence Tracking**: Measure analysis reliability
- **Probability Calculation**: Enable success probability estimation
- **Reporting**: Provide comprehensive target assessment
- **Decision Support**: Guide penetration testing strategy

## Procedure / Knowledge Detail

### Workflow Overview

**Input**: Single target identifier (URL, domain, IP, file path)

**Output**: Complete TargetProfile with all analysis metrics

### Seven-Step Analysis Pipeline

#### Step 1: Target Type Determination

**Method**: `_determine_target_type(target)`

**Logic**:
- Check URL patterns (http://, https://)
- Identify API endpoints (/api/ paths)
- Match IP address patterns (IPv4)
- Match domain name patterns
- Detect file types (.exe, .bin, .elf, .so, .dll)
- Identify cloud services (AWS, Azure, GCP)
- Default to UNKNOWN

**Output**: `TargetType` enum value

**Example**:

```python
target = "https://example.com/api/v1"
target_type = TargetType.API_ENDPOINT

target = "192.168.1.100"
target_type = TargetType.NETWORK_HOST

target = "/usr/bin/vulnerable_app"
target_type = TargetType.BINARY_FILE
```

#### Step 2: Domain Resolution (Conditional)

**Method**: `_resolve_domain(target)`

**Trigger**: Only for WEB_APPLICATION and API_ENDPOINT types

**Logic**:
- Extract hostname from URL if needed
- Use socket.gethostbyname() for DNS resolution
- Handle exceptions gracefully
- Return list of IP addresses

**Output**: List of IP addresses (empty if resolution fails)

**Example**:

```python
target = "https://example.com"
ip_addresses = ["93.184.216.34"]

target = "192.168.1.100"
ip_addresses = []  # Already an IP
```

#### Step 3: Technology Detection (Conditional)

**Method**: `_detect_technologies(target)`

**Trigger**: Only for WEB_APPLICATION type

**Logic**:
- Pattern matching on target string
- Check for WordPress indicators
- Check for PHP indicators
- Check for ASP.NET indicators
- Return list of detected technologies

**Output**: List of TechnologyStack values

**Example**:

```python
target = "https://wordpress.example.com"
technologies = [TechnologyStack.WORDPRESS, TechnologyStack.PHP]

target = "https://example.com"
technologies = []  # No patterns matched
```

#### Step 4: CMS Detection (Conditional)

**Method**: `_detect_cms(target)`

**Trigger**: Only for WEB_APPLICATION type

**Logic**:
- Pattern matching on target string
- Check for WordPress (wordpress, wp-)
- Check for Drupal
- Check for Joomla
- Return CMS type string or None

**Output**: CMS type string or None

**Example**:

```python
target = "https://wordpress.example.com"
cms_type = "WordPress"

target = "https://drupal.example.com"
cms_type = "Drupal"

target = "https://example.com"
cms_type = None
```

#### Step 5: Attack Surface Scoring

**Method**: `_calculate_attack_surface(profile)`

**Logic**:
- Base score by target type (3.0-8.0)
- Add technology factor (+0.5 per technology)
- Add port factor (+0.3 per open port)
- Add subdomain factor (+0.2 per subdomain)
- Add CMS bonus (+1.5 if detected)
- Normalize to 0-10 scale

**Output**: Float score (0.0-10.0)

**Example**:

```python
profile.target_type = TargetType.WEB_APPLICATION
profile.technologies = [APACHE, PHP]
profile.open_ports = [80, 443]
profile.cms_type = "WordPress"

attack_surface_score = 7.0 + 1.0 + 0.6 + 1.5 = 10.0
```

#### Step 6: Risk Level Classification

**Method**: `_determine_risk_level(profile)`

**Logic**:
- Compare attack_surface_score to thresholds
- Assign categorical risk level
- Critical: 8.0-10.0
- High: 6.0-7.9
- Medium: 4.0-5.9
- Low: 2.0-3.9
- Minimal: 0.0-1.9

**Output**: Risk level string

**Example**:

```python
profile.attack_surface_score = 8.5
risk_level = "critical"

profile.attack_surface_score = 5.2
risk_level = "medium"
```

#### Step 7: Confidence Score Calculation

**Method**: `_calculate_confidence(profile)`

**Logic**:
- Start with base confidence 0.5
- Add 0.1 if IP addresses resolved
- Add 0.2 if technologies detected
- Add 0.1 if CMS detected
- Add 0.1 if target type known
- Cap at 1.0

**Output**: Float confidence score (0.5-1.0)

**Example**:

```python
profile.ip_addresses = ["93.184.216.34"]  # +0.1
profile.technologies = [APACHE, PHP]      # +0.2
profile.cms_type = "WordPress"            # +0.1
profile.target_type = WEB_APPLICATION     # +0.1

confidence_score = 0.5 + 0.1 + 0.2 + 0.1 + 0.1 = 1.0
```

### Workflow Data Flow

```text
Input: Target String
    ↓
[Step 1: Target Type Determination]
    ├─ URL pattern? → WEB_APPLICATION/API_ENDPOINT
    ├─ IP pattern? → NETWORK_HOST
    ├─ File pattern? → BINARY_FILE
    ├─ Cloud pattern? → CLOUD_SERVICE
    └─ Default → UNKNOWN
    ↓
[Step 2: Domain Resolution] (Conditional: WEB_APP, API)
    ├─ Extract hostname
    ├─ DNS lookup
    └─ Return IP list
    ↓
[Step 3: Technology Detection] (Conditional: WEB_APP)
    ├─ Pattern matching
    ├─ Check WordPress, PHP, ASP.NET
    └─ Return tech list
    ↓
[Step 4: CMS Detection] (Conditional: WEB_APP)
    ├─ Pattern matching
    ├─ Check WordPress, Drupal, Joomla
    └─ Return CMS type
    ↓
[Step 5: Attack Surface Scoring]
    ├─ Base score by type
    ├─ Add factors
    └─ Return 0-10 score
    ↓
[Step 6: Risk Classification]
    ├─ Compare to thresholds
    └─ Return risk level
    ↓
[Step 7: Confidence Calculation]
    ├─ Incremental scoring
    └─ Return 0.5-1.0 score
    ↓
Output: Complete TargetProfile
```
