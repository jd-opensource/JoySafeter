# Technology Signature Detection System

## Overview

- **Purpose**: Detect web technologies using signature-based methods across HTTP headers, HTML content, and port patterns
- **Category**: detection
- **Severity**: high
- **Tags**: technology-detection, signature-based, web-servers, frameworks, cms, frontend-frameworks

## Context and Use-Cases

- **Technology fingerprinting**: Identify web servers, frameworks, and CMS platforms
- **Attack surface mapping**: Understand technology stack for targeted exploitation
- **Vulnerability assessment**: Match detected technologies to known vulnerabilities
- **Reconnaissance**: Gather intelligence during penetration testing
- **Security hardening**: Identify exposed technologies that should be hidden

## Procedure / Knowledge Detail

### Detection Methods

#### 1. HTTP Header-Based Detection

**Purpose**: Analyze HTTP response headers for technology signatures

**Supported Technologies**:

| Technology | Signatures | Detection Reliability |
|------------|-----------|----------------------|
| Apache | "Apache", "apache" | High |
| Nginx | "nginx", "Nginx" | High |
| IIS | "Microsoft-IIS", "IIS" | High |
| PHP | "PHP", "X-Powered-By: PHP" | High |
| Node.js | "Express", "X-Powered-By: Express" | High |
| Python | "Django", "Flask", "Werkzeug" | Medium |
| Java | "Tomcat", "JBoss", "WebLogic" | Medium |
| ASP.NET | "ASP.NET", "X-AspNet-Version" | High |

**Detection Process**:
1. Send HTTP request to target
2. Extract response headers
3. Compare against signature database
4. Return matched technologies

**Example Headers**:
```
Server: Apache/2.4.41 (Ubuntu)
X-Powered-By: PHP/7.4.3
X-AspNet-Version: 4.0.30319
```

#### 2. HTML Content-Based Detection

**Purpose**: Analyze HTML content for technology signatures

**Supported Technologies**:

| Technology | Signatures | Detection Reliability |
|------------|-----------|----------------------|
| WordPress | "wp-content", "wp-includes", "WordPress" | High |
| Drupal | "Drupal", "drupal", "/sites/default" | High |
| Joomla | "Joomla", "joomla", "/administrator" | High |
| React | "React", "react", "__REACT_DEVTOOLS" | Medium |
| Angular | "Angular", "angular", "ng-version" | Medium |
| Vue | "Vue", "vue", "__VUE__" | Medium |

**Detection Process**:
1. Fetch HTML content from target
2. Search for content signatures
3. Check for framework-specific directories
4. Return matched technologies

**Example Content Signatures**:
```html
<!-- WordPress -->
<link rel="stylesheet" href="/wp-content/themes/...">
<script src="/wp-includes/js/..."></script>

<!-- React -->
<div id="root"></div>
<script>window.__REACT_DEVTOOLS__</script>

<!-- Angular -->
<html ng-app="myApp">
<meta name="ng-version" content="12.0.0">
```

#### 3. Port-Based Detection

**Purpose**: Infer technologies based on open ports and services

**Supported Technologies**:

| Technology | Ports | Detection Reliability |
|------------|-------|----------------------|
| Apache | 80, 443, 8080, 8443 | Low (common ports) |
| Nginx | 80, 443, 8080 | Low (common ports) |
| IIS | 80, 443, 8080 | Low (common ports) |
| Node.js | 3000, 8000, 8080, 9000 | Medium (specific ports) |

**Detection Process**:
1. Perform port scan on target
2. Identify open ports
3. Match against port signature database
4. Combine with service detection
5. Return inferred technologies

**Limitations**:
- Many technologies use standard ports (80, 443)
- Port-based detection has high false positive rate
- Should be combined with header/content detection

### Detection Workflow

#### Phase 1: Header Analysis
1. Send HTTP request to target
2. Extract all response headers
3. Compare against header signature database
4. Record matched technologies

#### Phase 2: Content Analysis
1. Fetch HTML content from target
2. Search for content signatures
3. Check for framework-specific paths
4. Record matched technologies

#### Phase 3: Port Analysis
1. Perform port scan (if available)
2. Identify open ports
3. Match against port signature database
4. Record inferred technologies

#### Phase 4: Consolidation
1. Combine results from all methods
2. Assign confidence scores
3. Prioritize high-confidence matches
4. Return consolidated technology list
