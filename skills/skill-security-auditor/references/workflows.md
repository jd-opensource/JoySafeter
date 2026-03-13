# Workflows

# Skill Security Auditor Workflows

## Metadata validation

- parse_frontmatter: skill_path target SKILL.md
- validate_skill_name: compare frontmatter name with directory name
- validate_version: check semver format
- validate_metadata_fields: check completeness
- validate_requires_bins: check for dangerous binaries
- Check for:
  - Missing frontmatter: SKILL.md must have valid YAML frontmatter
  - Name mismatch: name field must match directory name
  - Invalid version: must follow semver (MAJOR.MINOR.PATCH)
  - Missing description: description field must not be empty
  - Dangerous binary requirements: nc, ncat, socat, nmap, msfconsole trigger HIGH alert
  - Self-declared risk "unsafe": triggers HIGH alert, requires justification
  - Missing category: makes skill harder to classify for security review

## Prompt injection scanning

- scan_prompt_injection: content from SKILL.md full text
- detect_role_hijack: patterns
  - "You are now a"
  - "Ignore (all )?(previous |prior )?instructions"
  - "Act as (a |an )?"
  - "Forget (your |all )?(previous )?(instructions|rules|constraints)"
  - "From now on"
  - "New persona:"
- detect_instruction_override: patterns
  - "Do not follow (any )?(previous |prior )?(rules|instructions)"
  - "Override (the )?system prompt"
  - "New (system )?instructions:"
  - "Disregard (all )?(safety |security )?(measures|checks|rules)"
  - "Disable (safety|security|content) (filter|check)"
- detect_hidden_directives:
  - HTML comments: `<!-- instructions here -->`
  - CSS hidden: `<span style="display:none">`, `<div style="font-size:0">`
  - Markdown reference links with instruction text: `[//]: # (hidden instruction)`
  - Image alt text with instructions
- detect_zero_width_chars: scan every character
  - U+200B Zero Width Space
  - U+200C Zero Width Non-Joiner
  - U+200D Zero Width Joiner
  - U+FEFF Zero Width No-Break Space (BOM)
  - U+2060 Word Joiner
  - If found: decode_hidden_content to reveal what's hidden
- detect_bidi_attacks: scan for directional override
  - U+202A Left-to-Right Embedding
  - U+202B Right-to-Left Embedding
  - U+202C Pop Directional Formatting
  - U+202D Left-to-Right Override
  - U+202E Right-to-Left Override (most dangerous: can make "exec" look like "cexe")
  - U+2066-U+2069 Isolate variants

## Code block security audit

- extract_code_blocks: from SKILL.md content
- For each code block by language:
  - Bash/Shell blocks:
    - scan_bash_block: reverse shell patterns, exfiltration, privilege escalation
    - detect_download_execute: curl|bash, wget|sh patterns
    - detect_obfuscation: base64 pipes, variable construction
  - Python blocks:
    - scan_python_block: exec(), eval(), __import__, subprocess, os.system, socket
    - Check for: importlib.import_module, compile+exec, pickle.loads (arbitrary code execution)
    - detect_obfuscation: exec(bytes.fromhex()), exec(__import__('base64').b64decode())
  - JavaScript blocks:
    - scan_javascript_block: eval, Function(), child_process, require('net'), require('fs')
    - Check for: vm.runInNewContext, WebAssembly (code execution), fetch to external origins
    - detect_obfuscation: String.fromCharCode, atob, unescape
  - All languages:
    - detect_download_execute: language-appropriate patterns
    - detect_obfuscation: multi-layer encoding detection
    - Check for file writes to sensitive locations: .bashrc, .profile, crontab, authorized_keys
    - Check for environment variable reads: process.env, os.environ, $ENV_VAR for sensitive keys

## Dependency and reference audit

- extract_urls: from all content (SKILL.md + references/)
- For each URL:
  - check_url_safety: HTTPS check, domain reputation
  - Flag: HTTP URLs (MEDIUM), known-malicious domains (CRITICAL), IP addresses (MEDIUM)
- For each referenced package:
  - detect_typosquatting: compare against top 1000 packages in ecosystem
    - Edit distance <= 2 from popular package: HIGH
    - Visual similarity (l/1, O/0, rn/m): HIGH
  - check_package_exists: verify package is real and active
    - Package not found: HIGH (may be dependency confusion)
    - Package archived/deprecated: LOW
    - Very low downloads (<100/week): MEDIUM (possibly malicious clone)
  - check_install_hooks: detect preinstall/postinstall scripts
    - Hooks present: flag for manual review (MEDIUM)
    - Hooks with network calls: HIGH
    - Hooks with eval/exec: CRITICAL

## File structure validation

- validate_skill_structure: skill_dir
  - Required: SKILL.md
  - Optional: references/, scripts/, examples/
  - Unexpected: anything else warrants inspection
- detect_binary_files: flag non-text files
  - Exceptions: images for documentation (.png, .jpg, .svg) — LOW
  - All other binaries: HIGH
- detect_executable_files: flag +x permission
  - Scripts (.sh, .py) with +x: MEDIUM (check if justified)
  - Other files with +x: HIGH
- detect_symlinks: check for directory escape
  - Symlink target within skill dir: LOW (informational)
  - Symlink target outside skill dir: CRITICAL (potential escape attack)
- detect_hidden_files:
  - .env: HIGH (may contain secrets)
  - .git: MEDIUM (may contain history with secrets)
  - .npmrc, .pypirc: HIGH (may contain registry tokens)
  - Other dot files: LOW (informational)
- check_file_sizes: flag files > 1MB
  - Markdown > 1MB: MEDIUM (unusually large, check for embedded data)
  - Any file > 10MB: HIGH (bloat or embedded binary data)

## Permission scope analysis

- analyze_declared_permissions: from metadata
- For each code block and reference:
  - detect_undeclared_operations: cross-reference code behavior vs declarations
    - Network access in code but not declared in requires: HIGH
    - File write outside workspace in code but risk marked "safe": HIGH
    - Command execution (subprocess, exec) but not declared: MEDIUM
- assess_permission_scope:
  - Scope proportionality: does a "documentation helper" skill really need network access?
  - Least privilege check: are requested permissions minimal for stated purpose?

## Version update audit

- diff_skill_versions: old_path (cached/previous), new_path (incoming)
- analyze_diff_risk:
  - New code blocks added: re-run full code block audit on additions
  - New URLs added: check each new URL for safety
  - Permission changes in metadata: flag any escalation
  - New binary dependencies added: flag for review
  - Removed safety disclaimers or warnings: MEDIUM
  - Changes to frontmatter name/category: MEDIUM (possible identity swap)

## Final verdict

- calculate_risk_score: from all findings
- generate_audit_report: format based on caller preference
- Verdict determination:
  - **PASS** (risk_score < 20): No CRITICAL or HIGH findings. Safe to load.
  - **CONDITIONAL** (20 <= risk_score < 50): HIGH findings present but no CRITICAL. Requires human review and explicit approval before loading.
  - **REJECT** (risk_score >= 50): CRITICAL findings present. Skill must NOT be loaded. Move to _quarantine directory with audit report attached.
- Post-verdict actions:
  - PASS: generate hash baseline for version tracking
  - CONDITIONAL: notify reviewer with findings summary
  - REJECT: quarantine skill, log rejection reason, notify admin
