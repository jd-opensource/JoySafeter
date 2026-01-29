# File Upload Testing Workflow

## Overview
- Purpose: Comprehensive workflow for identifying and testing file upload vulnerabilities
- Category: web_security
- Severity: high
- Tags: file-upload, testing-workflow, vulnerability-assessment, web-security, OWASP-A4

## Context and Use-Cases
- File upload functionality is a common attack vector in web applications
- Systematic testing helps identify multiple layers of validation weaknesses
- Structured workflow ensures comprehensive coverage of all attack vectors
- Estimated time: 360 minutes (6 hours) for complete testing
- Risk level: High

## Testing Phases

### Phase 1: Reconnaissance
**Name:** reconnaissance
**Description:** Identify upload endpoints and entry points

**Tools:**
- `katana` - Web crawler for endpoint discovery
- `gau` - Get All URLs from web archives
- `paramspider` - Parameter discovery

**Expected Findings:**
- Upload forms (file input fields)
- API endpoints accepting file uploads
- Hidden upload endpoints
- File management interfaces

**Procedure:**
1. Use katana to crawl target application
2. Identify all forms with file input fields
3. Use gau to find historical upload endpoints
4. Use paramspider to discover upload-related parameters
5. Document all upload endpoints and their locations

### Phase 2: Baseline Testing
**Name:** baseline_testing
**Description:** Test legitimate file uploads to understand normal behavior

**Test Files:**
- `image.jpg` - Standard image file
- `document.pdf` - PDF document
- `text.txt` - Plain text file

**Observations to Record:**
- Response codes (200, 201, 400, 413, etc.)
- File storage locations (if accessible)
- Naming conventions (original name, hashed, sequential)
- File access URLs
- Upload restrictions (size, type)
- Error messages

**Procedure:**
1. Upload each legitimate test file
2. Record HTTP response codes and messages
3. Attempt to access uploaded files
4. Note any file renaming or path changes
5. Check for file metadata preservation
6. Test upload size limits

### Phase 3: Malicious Upload Testing
**Name:** malicious_upload_testing
**Description:** Test malicious file uploads with various bypass techniques

**Bypass Techniques:**
- `double_extension` - shell.php.txt
- `null_byte` - shell.php%00.txt
- `content_type_spoofing` - Claim as image/jpeg
- `magic_bytes` - GIF89a + PHP code
- `case_variation` - shell.PhP
- `special_characters` - shell.php. or shell.php%20

**Test Files Generated:**
- Web shells (PHP, ASP, JSP)
- Polyglot files (image + code)
- Files with various extension combinations

**Procedure:**
1. Generate test files for each bypass technique
2. Attempt upload with each technique
3. Record success/failure for each attempt
4. Note any error messages or restrictions
5. Test multiple file types (PHP, ASP, JSP, etc.)
6. Test polyglot files (image + executable code)

### Phase 4: Post-Upload Verification
**Name:** post_upload_verification
**Description:** Verify uploaded files and test execution capabilities

**Actions:**
- `file_access_test` - Attempt to access uploaded file via URL
- `execution_test` - Verify if uploaded code executes
- `path_traversal_test` - Test for directory traversal vulnerabilities

**Procedure:**
1. **File Access Test:**
   - Construct URL to uploaded file
   - Attempt direct access via browser/curl
   - Check if file is accessible

2. **Execution Test:**
   - For web shells: attempt command execution
   - Test with simple commands (id, whoami, ls)
   - Verify output in response

3. **Path Traversal Test:**
   - Try uploading to parent directories (../../../)
   - Test for directory traversal in upload path
   - Attempt to overwrite existing files

## Examples

### Complete Testing Workflow
```python
def create_upload_testing_workflow(target_url: str) -> Dict[str, Any]:
    """Create comprehensive file upload testing workflow"""
    workflow = {
        "target": target_url,
        "test_phases": [
            {
                "name": "reconnaissance",
                "description": "Identify upload endpoints",
                "tools": ["katana", "gau", "paramspider"],
                "expected_findings": ["upload_forms", "api_endpoints"]
            },
            {
                "name": "baseline_testing",
                "description": "Test legitimate file uploads",
                "test_files": ["image.jpg", "document.pdf", "text.txt"],
                "observations": ["response_codes", "file_locations", "naming_conventions"]
            },
            {
                "name": "malicious_upload_testing",
                "description": "Test malicious file uploads",
                "test_files": generate_test_files(),
                "bypass_techniques": [
                    "double_extension",
                    "null_byte",
                    "content_type_spoofing",
                    "magic_bytes",
                    "case_variation",
                    "special_characters"
                ]
            },
            {
                "name": "post_upload_verification",
                "description": "Verify uploaded files and test execution",
                "actions": ["file_access_test", "execution_test", "path_traversal_test"]
            }
        ],
        "estimated_time": 360,
        "risk_level": "high"
    }
    return workflow
```

### Reconnaissance Commands
```bash
# Discover upload endpoints with katana
katana -u https://target.com -d 3

# Get historical URLs from archives
gau https://target.com | grep -i upload

# Discover upload parameters
paramspider -d target.com -s
```

### Baseline Testing
```bash
# Upload legitimate file
curl -F "file=@image.jpg" https://target.com/upload

# Record response
# Check file location
# Attempt access
curl https://target.com/uploads/image.jpg
```

### Malicious Testing
```bash
# Double extension
curl -F "file=@shell.php.txt" https://target.com/upload

# Content-Type spoofing
curl -F "file=@shell.php;type=image/jpeg" https://target.com/upload

# Null byte
curl -F "file=@shell.php%00.jpg" https://target.com/upload
```

### Verification
```bash
# Test web shell execution
curl "https://target.com/uploads/shell.php?cmd=id"

# Test path traversal
curl -F "file=@shell.php" "https://target.com/upload?path=../../../"
```

## Risk Assessment
- **Risk Level:** High
- **OWASP:** A4:2021 – Insecure File Upload
- **CWE:** CWE-434 (Unrestricted Upload of File with Dangerous Type)
- **Impact:** Remote Code Execution (RCE), Server Compromise

## Remediation Recommendations
1. Implement strict file type validation (whitelist)
2. Validate file content (magic bytes), not just extension
3. Store uploads outside web root
4. Disable script execution in upload directories
5. Rename uploaded files
6. Implement access controls
7. Scan files with antivirus/malware detection
8. Log and monitor upload activities
9. Use dedicated file storage services
10. Implement file size limits
