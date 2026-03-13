# Tools

# Skill Security Auditor Tools

## Common response fields

- success: boolean
- finding_id: unique identifier for each finding
- severity: "CRITICAL"|"HIGH"|"MEDIUM"|"LOW"
- category: audit category string
- location: file path and line number of finding
- recommendation: suggested remediation

## Metadata validation

- parse_frontmatter(skill_path): Parse SKILL.md YAML frontmatter and return structured metadata. Validates presence of required fields (name, description, version). Returns parsed metadata or validation errors.
- validate_skill_name(name, directory_name): Check if frontmatter name matches the containing directory name. Returns match status and both names.
- validate_version(version): Verify version string follows semver format. Returns validity status.
- validate_metadata_fields(metadata): Check metadata completeness (category, risk, requires). Returns missing/invalid fields.
- validate_requires_bins(bins_list): Check declared binary dependencies against a list of known-dangerous binaries (nc, ncat, socat, nmap). Returns risk assessment per binary.

## Prompt injection scanning

- scan_prompt_injection(content, check_zero_width=True, check_bidi=True, check_html_comments=True): Comprehensive prompt injection scan on text content. Returns array of injection indicators with matched patterns and line numbers.
- detect_role_hijack(content): Search for role override patterns ("You are now", "Ignore previous", "Act as", "Forget your instructions"). Returns matches with context.
- detect_instruction_override(content): Search for instruction override patterns ("Do not follow", "Override system", "New instructions"). Returns matches.
- detect_hidden_directives(content): Search for directives hidden in HTML comments, CSS display:none, Markdown reference links. Returns hidden content found.
- detect_zero_width_chars(content): Scan for zero-width Unicode characters (U+200B/C/D, U+FEFF) that could hide instructions. Returns positions and surrounding context.
- detect_bidi_attacks(content): Scan for Bidi override characters (U+202A-U+202E, U+2066-U+2069) that change text display direction. Returns affected ranges.
- decode_hidden_content(content, positions): Attempt to decode/reveal content hidden by zero-width or Bidi characters. Returns decoded text.

## Code block analysis

- extract_code_blocks(markdown_content): Extract all fenced code blocks from Markdown with language hints, line numbers, and raw content. Returns array of code block objects.
- scan_bash_block(code): Analyze bash code block for dangerous patterns (reverse shells, data exfiltration, privilege escalation). Returns findings.
- scan_python_block(code): Analyze Python code block for dangerous patterns (exec, eval, subprocess, socket, os.system, importlib). Returns findings.
- scan_javascript_block(code): Analyze JavaScript code block for dangerous patterns (child_process, eval, Function, require('net'), fetch to external). Returns findings.
- detect_download_execute(code, language): Detect download-and-execute patterns across languages (curl|sh, wget|bash, python -c "$(curl...)"). Returns findings.
- detect_obfuscation(code): Detect obfuscation techniques (base64 encoding, hex escapes, string concatenation tricks, eval chains). Returns obfuscation indicators with best-effort decoded content.

## Dependency and reference checking

- extract_urls(content): Extract all URLs from Skill content (Markdown links, code blocks, plain text). Returns URL list with context.
- check_url_safety(url): Verify URL uses HTTPS, check domain reputation, detect known-malicious domains. Returns safety assessment.
- detect_typosquatting(package_name, ecosystem="npm"): Compare package name against known popular packages using edit distance and visual similarity. Returns similarity matches above threshold (0.8).
- check_package_exists(package_name, ecosystem="npm"): Verify if a referenced package actually exists on the registry. Returns existence and basic metadata (downloads, last publish, maintainer).
- check_install_hooks(package_name, ecosystem="npm"): Check if a package has preinstall/postinstall hooks that execute code. Returns hook presence and content.

## File structure validation

- validate_skill_structure(skill_dir): Check directory structure against expected layout (SKILL.md required, optional references/). Returns structure assessment.
- detect_binary_files(skill_dir): Scan for non-text files using file magic bytes. Returns list of binary files found.
- detect_executable_files(skill_dir): Scan for files with executable permission bits. Returns list with permission details.
- detect_symlinks(skill_dir): Find symbolic links and verify they don't point outside the skill directory (symlink escape). Returns symlink list with targets and safety status.
- detect_hidden_files(skill_dir): Find dot-prefixed hidden files (.env, .git, .npmrc). Returns list with risk assessment.
- check_file_sizes(skill_dir, max_size_bytes=1048576): Flag files exceeding size limit. Returns oversized files.

## Permission analysis

- analyze_declared_permissions(metadata): Parse the metadata.requires and metadata.risk fields to understand what the skill claims it needs. Returns permission summary.
- detect_undeclared_operations(code_blocks, declared_permissions): Cross-reference operations found in code blocks against declared permissions. Returns undeclared operations (network access, file writes, command execution not matching declarations).
- assess_permission_scope(operations): Evaluate whether the scope of operations (filesystem paths, network targets) is proportional to the skill's stated purpose. Returns scope assessment.

## Version diff analysis

- diff_skill_versions(old_path, new_path): Compare two versions of a skill and generate a structured diff. Returns added/modified/deleted content with security-relevant annotations.
- analyze_diff_risk(diff): Assess the security risk of changes between versions (new code blocks, new URLs, permission changes, new dependencies). Returns risk assessment of the update.

## Reporting

- generate_audit_report(findings, skill_metadata, format="json"): Generate formatted audit report. format: "json"|"markdown"|"text". Returns structured report with verdict (PASS/CONDITIONAL/REJECT).
- calculate_risk_score(findings): Compute overall risk score (0-100, higher = more risky) from findings. Returns score with breakdown.
