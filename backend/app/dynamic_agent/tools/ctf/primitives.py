"""
CTF Primitives Module

Provides shell/Python action templates and risk guards for CTF challenges:
- Safe command templates for common CTF operations
- Risk level assessment for commands
- Action generation from reference hits and user hints
"""

import re
import shlex
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.dynamic_agent.core.constants import (
    CTF_PYTHON_TOOL_PATTERNS,
    CTF_SHELL_TOOL_PATTERNS,
    CtfRiskLevel,
    CtfToolType,
)
from app.dynamic_agent.storage.session.ctf import ReferenceHit, UserHint

# =============================================================================
# Risk Assessment
# =============================================================================

# Commands that are always safe (read-only, non-destructive)
SAFE_COMMANDS = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "grep",
    "rg",
    "find",
    "ls",
    "pwd",
    "echo",
    "printf",
    "wc",
    "sort",
    "uniq",
    "cut",
    "tr",
    "sed",
    "awk",
    "file",
    "strings",
    "xxd",
    "hexdump",
    "od",
    "base64",
    "openssl",
    "curl",
    "wget",
    "nc",
    "netcat",
    "ncat",
    "socat",
    "python",
    "python3",
    "python2",
    "perl",
    "ruby",
    "node",
    "nmap",
    "nikto",
    "gobuster",
    "dirb",
    "sqlmap",
    "hydra",
    "binwalk",
    "foremost",
    "exiftool",
    "steghide",
    "zsteg",
    "gdb",
    "objdump",
    "readelf",
    "nm",
    "ltrace",
    "strace",
    "john",
    "hashcat",
    "aircrack-ng",
}

# Commands that require confirmation (potentially destructive)
MEDIUM_RISK_COMMANDS = {
    "rm",
    "mv",
    "cp",
    "mkdir",
    "rmdir",
    "touch",
    "chmod",
    "chown",
    "chgrp",
    "pip",
    "pip3",
    "npm",
    "apt",
    "yum",
    "brew",
    "docker",
    "kubectl",
    "ssh",
    "scp",
    "rsync",
}

# Commands that are high risk (system-level, destructive)
HIGH_RISK_COMMANDS = {
    "sudo",
    "su",
    "passwd",
    "useradd",
    "userdel",
    "dd",
    "mkfs",
    "fdisk",
    "parted",
    "iptables",
    "ufw",
    "firewall-cmd",
    "systemctl",
    "service",
    "init",
    "reboot",
    "shutdown",
    "halt",
    "poweroff",
    "kill",
    "killall",
    "pkill",
}

# Dangerous patterns in commands
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",  # rm -rf /
    r">\s*/dev/",  # Redirect to device
    r":\(\)\s*{\s*:\|:&\s*};:",  # Fork bomb
    r"\|\s*sh\b",  # Pipe to shell
    r"\|\s*bash\b",  # Pipe to bash
    r"`.*`",  # Command substitution (backticks)
    r"\$\(.*\)",  # Command substitution
    r"eval\s+",  # Eval command
    r"exec\s+",  # Exec command
]


def assess_command_risk(command: str) -> Tuple[CtfRiskLevel, str]:
    """
    Assess the risk level of a shell command.

    Args:
        command: Shell command to assess

    Returns:
        Tuple of (risk_level, reason)
    """
    command_lower = command.lower().strip()

    # Check for dangerous patterns first
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower):
            return CtfRiskLevel.HIGH, f"Dangerous pattern detected: {pattern}"

    # Extract the base command
    try:
        parts = shlex.split(command)
        if not parts:
            return CtfRiskLevel.LOW, "Empty command"
        base_cmd = parts[0].split("/")[-1]  # Handle full paths
    except ValueError:
        # Shlex parsing failed, try simple split
        base_cmd = command.split()[0].split("/")[-1] if command.split() else ""

    # Check risk levels
    if base_cmd in HIGH_RISK_COMMANDS:
        return CtfRiskLevel.HIGH, f"High-risk command: {base_cmd}"

    if base_cmd in MEDIUM_RISK_COMMANDS:
        return CtfRiskLevel.MEDIUM, f"Medium-risk command: {base_cmd}"

    if base_cmd in SAFE_COMMANDS:
        return CtfRiskLevel.LOW, f"Safe command: {base_cmd}"

    # Unknown command - default to medium risk
    return CtfRiskLevel.MEDIUM, f"Unknown command: {base_cmd}"


def assess_python_risk(code: str) -> Tuple[CtfRiskLevel, str]:
    """
    Assess the risk level of Python code.

    Args:
        code: Python code to assess

    Returns:
        Tuple of (risk_level, reason)
    """
    code_lower = code.lower()

    # High-risk patterns
    high_risk_patterns = [
        (r"\bos\.system\b", "os.system call"),
        (r"\bsubprocess\.call\b", "subprocess.call"),
        (r"\bsubprocess\.run\b", "subprocess.run"),
        (r"\bexec\s*\(", "exec() call"),
        (r"\beval\s*\(", "eval() call"),
        (r"\b__import__\s*\(", "__import__() call"),
        (r'\bopen\s*\([^)]*["\']w', "File write operation"),
        (r"\bshutil\.rmtree\b", "shutil.rmtree"),
        (r"\bos\.remove\b", "os.remove"),
        (r"\bos\.unlink\b", "os.unlink"),
    ]

    for pattern, reason in high_risk_patterns:
        if re.search(pattern, code_lower):
            return CtfRiskLevel.HIGH, reason

    # Medium-risk patterns
    medium_risk_patterns = [
        (r"\brequests\.(post|put|delete)\b", "HTTP mutation request"),
        (r"\bsocket\b", "Socket operations"),
        (r"\bparamiko\b", "SSH operations"),
        (r"\bftplib\b", "FTP operations"),
    ]

    for pattern, reason in medium_risk_patterns:
        if re.search(pattern, code_lower):
            return CtfRiskLevel.MEDIUM, reason

    # Safe patterns (common CTF operations)
    safe_patterns = [
        r"\bbase64\b",
        r"\bhashlib\b",
        r"\bCrypto\b",
        r"\bpwntools\b",
        r"\bstruct\b",
        r"\bbinascii\b",
        r"\brequests\.get\b",
        r"\bprint\s*\(",
    ]

    for pattern in safe_patterns:
        if re.search(pattern, code_lower):
            return CtfRiskLevel.LOW, "Common CTF operation"

    # Default to low risk for simple code
    return CtfRiskLevel.LOW, "No risky patterns detected"


# =============================================================================
# Action Templates
# =============================================================================


@dataclass
class ActionTemplate:
    """Template for CTF actions."""

    name: str
    tool_type: CtfToolType
    template: str
    description: str
    risk_level: CtfRiskLevel
    parameters: List[str]
    category: str  # crypto, pwn, web, misc, etc.


# Common CTF action templates
CTF_ACTION_TEMPLATES: Dict[str, ActionTemplate] = {
    # Crypto templates
    "base64_decode": ActionTemplate(
        name="base64_decode",
        tool_type=CtfToolType.SHELL,
        template="echo '{input}' | base64 -d",
        description="Decode base64 encoded string",
        risk_level=CtfRiskLevel.LOW,
        parameters=["input"],
        category="crypto",
    ),
    "base64_encode": ActionTemplate(
        name="base64_encode",
        tool_type=CtfToolType.SHELL,
        template="echo -n '{input}' | base64",
        description="Encode string to base64",
        risk_level=CtfRiskLevel.LOW,
        parameters=["input"],
        category="crypto",
    ),
    "hex_decode": ActionTemplate(
        name="hex_decode",
        tool_type=CtfToolType.PYTHON,
        template="print(bytes.fromhex('{input}').decode())",
        description="Decode hex string",
        risk_level=CtfRiskLevel.LOW,
        parameters=["input"],
        category="crypto",
    ),
    "rot13": ActionTemplate(
        name="rot13",
        tool_type=CtfToolType.SHELL,
        template="echo '{input}' | tr 'A-Za-z' 'N-ZA-Mn-za-m'",
        description="Apply ROT13 cipher",
        risk_level=CtfRiskLevel.LOW,
        parameters=["input"],
        category="crypto",
    ),
    "xor_decrypt": ActionTemplate(
        name="xor_decrypt",
        tool_type=CtfToolType.PYTHON,
        template="print(''.join(chr(ord(c) ^ {key}) for c in '{input}'))",
        description="XOR decrypt with single-byte key",
        risk_level=CtfRiskLevel.LOW,
        parameters=["input", "key"],
        category="crypto",
    ),
    # Web templates
    "curl_get": ActionTemplate(
        name="curl_get",
        tool_type=CtfToolType.SHELL,
        template="curl -s '{url}'",
        description="HTTP GET request",
        risk_level=CtfRiskLevel.LOW,
        parameters=["url"],
        category="web",
    ),
    "curl_post": ActionTemplate(
        name="curl_post",
        tool_type=CtfToolType.SHELL,
        template="curl -s -X POST -d '{data}' '{url}'",
        description="HTTP POST request",
        risk_level=CtfRiskLevel.LOW,
        parameters=["url", "data"],
        category="web",
    ),
    "curl_headers": ActionTemplate(
        name="curl_headers",
        tool_type=CtfToolType.SHELL,
        template="curl -s -I '{url}'",
        description="Get HTTP headers",
        risk_level=CtfRiskLevel.LOW,
        parameters=["url"],
        category="web",
    ),
    # Pwn templates
    "nc_connect": ActionTemplate(
        name="nc_connect",
        tool_type=CtfToolType.SHELL,
        template="nc {host} {port}",
        description="Connect to remote host with netcat",
        risk_level=CtfRiskLevel.LOW,
        parameters=["host", "port"],
        category="pwn",
    ),
    "nc_send": ActionTemplate(
        name="nc_send",
        tool_type=CtfToolType.SHELL,
        template="echo '{payload}' | nc {host} {port}",
        description="Send payload via netcat",
        risk_level=CtfRiskLevel.LOW,
        parameters=["host", "port", "payload"],
        category="pwn",
    ),
    "pwntools_connect": ActionTemplate(
        name="pwntools_connect",
        tool_type=CtfToolType.PYTHON,
        template="from pwn import *; r = remote('{host}', {port}); print(r.recvall().decode())",
        description="Connect using pwntools",
        risk_level=CtfRiskLevel.LOW,
        parameters=["host", "port"],
        category="pwn",
    ),
    # Misc templates
    "strings_extract": ActionTemplate(
        name="strings_extract",
        tool_type=CtfToolType.SHELL,
        template="strings '{file}' | grep -i flag",
        description="Extract strings and search for flag",
        risk_level=CtfRiskLevel.LOW,
        parameters=["file"],
        category="misc",
    ),
    "file_info": ActionTemplate(
        name="file_info",
        tool_type=CtfToolType.SHELL,
        template="file '{file}'",
        description="Get file type information",
        risk_level=CtfRiskLevel.LOW,
        parameters=["file"],
        category="misc",
    ),
    "binwalk_extract": ActionTemplate(
        name="binwalk_extract",
        tool_type=CtfToolType.SHELL,
        template="binwalk -e '{file}'",
        description="Extract embedded files with binwalk",
        risk_level=CtfRiskLevel.MEDIUM,
        parameters=["file"],
        category="misc",
    ),
    "exiftool_metadata": ActionTemplate(
        name="exiftool_metadata",
        tool_type=CtfToolType.SHELL,
        template="exiftool '{file}'",
        description="Extract file metadata",
        risk_level=CtfRiskLevel.LOW,
        parameters=["file"],
        category="misc",
    ),
}


def get_template(name: str) -> Optional[ActionTemplate]:
    """Get an action template by name."""
    return CTF_ACTION_TEMPLATES.get(name)


def get_templates_by_category(category: str) -> List[ActionTemplate]:
    """Get all templates for a category."""
    return [t for t in CTF_ACTION_TEMPLATES.values() if t.category == category]


def render_template(template: ActionTemplate, **params) -> str:
    """
    Render an action template with parameters.

    Args:
        template: Action template to render
        **params: Parameter values

    Returns:
        Rendered command/code string
    """
    result = template.template
    for param in template.parameters:
        if param in params:
            # Escape single quotes in shell commands
            value = str(params[param])
            if template.tool_type == CtfToolType.SHELL:
                value = value.replace("'", "'\"'\"'")
            result = result.replace(f"{{{param}}}", value)
    return result


# =============================================================================
# Action Generation
# =============================================================================


def classify_tool_type(tool_name: str) -> CtfToolType:
    """
    Classify a tool name into CTF tool type.

    Args:
        tool_name: Name of the tool

    Returns:
        CtfToolType classification
    """
    tool_lower = tool_name.lower()

    # Check shell patterns
    for pattern in CTF_SHELL_TOOL_PATTERNS:
        if pattern in tool_lower:
            return CtfToolType.SHELL

    # Check python patterns
    for pattern in CTF_PYTHON_TOOL_PATTERNS:
        if pattern in tool_lower:
            return CtfToolType.PYTHON

    return CtfToolType.OTHER


def generate_action_from_hint(
    hint: UserHint,
    challenge_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate an action from a user hint.

    Args:
        hint: User hint to process
        challenge_type: Type of CTF challenge

    Returns:
        Action dict with tool_type, command, and risk_level, or None
    """
    content = hint.content.lower()

    # Try to match hint to templates
    template_matches: list[tuple[str, dict[str, Any]]] = []

    # Check for encoding/decoding hints
    if any(kw in content for kw in ["base64", "decode", "encode"]):
        if "decode" in content:
            template_matches.append(("base64_decode", {}))
        else:
            template_matches.append(("base64_encode", {}))

    if any(kw in content for kw in ["hex", "hexadecimal"]):
        template_matches.append(("hex_decode", {}))

    if any(kw in content for kw in ["rot13", "caesar", "rotate"]):
        template_matches.append(("rot13", {}))

    if any(kw in content for kw in ["xor", "exclusive or"]):
        template_matches.append(("xor_decrypt", {}))

    # Check for web hints
    if any(kw in content for kw in ["curl", "http", "get", "request", "url"]):
        if "post" in content:
            template_matches.append(("curl_post", {}))
        else:
            template_matches.append(("curl_get", {}))

    # Check for pwn hints
    if any(kw in content for kw in ["nc", "netcat", "connect", "port"]):
        template_matches.append(("nc_connect", {}))

    # Check for misc hints
    if any(kw in content for kw in ["strings", "extract"]):
        template_matches.append(("strings_extract", {}))

    if any(kw in content for kw in ["file", "type", "info"]):
        template_matches.append(("file_info", {}))

    if any(kw in content for kw in ["binwalk", "embedded"]):
        template_matches.append(("binwalk_extract", {}))

    if any(kw in content for kw in ["exif", "metadata"]):
        template_matches.append(("exiftool_metadata", {}))

    # Return first match
    if template_matches:
        template_name, params = template_matches[0]
        template = get_template(template_name)
        if template:
            return {
                "tool_type": template.tool_type,
                "template_name": template_name,
                "description": template.description,
                "risk_level": template.risk_level,
                "category": template.category,
            }

    return None


def generate_action_from_reference(
    reference: ReferenceHit,
    challenge_type: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate an action suggestion from a reference hit.

    Args:
        reference: Reference hit to process
        challenge_type: Type of CTF challenge

    Returns:
        Action suggestion dict or None
    """
    if not reference.snippet:
        return None

    snippet = reference.snippet.lower()

    # Look for command patterns in snippet
    command_patterns = [
        (r"curl\s+[^\n]+", "curl_get", CtfToolType.SHELL),
        (r"nc\s+\S+\s+\d+", "nc_connect", CtfToolType.SHELL),
        (r"base64\s+-d", "base64_decode", CtfToolType.SHELL),
        (r"strings\s+", "strings_extract", CtfToolType.SHELL),
        (r"python.*-c", "python_code", CtfToolType.PYTHON),
    ]

    for pattern, template_name, tool_type in command_patterns:
        match = re.search(pattern, snippet)
        if match:
            return {
                "tool_type": tool_type,
                "template_name": template_name,
                "suggested_command": match.group(0),
                "source": reference.location,
                "confidence": reference.confidence,
            }

    return None


def prioritize_tools(
    available_tools: List[str],
    is_ctf: bool = True,
) -> List[str]:
    """
    Prioritize tools for CTF mode.

    Args:
        available_tools: List of available tool names
        is_ctf: Whether CTF mode is active

    Returns:
        Reordered list with python/shell tools first
        Python tools are prioritized for complex tasks (enumeration, crypto)
    """
    if not is_ctf:
        return available_tools

    shell_tools = []
    python_tools = []
    other_tools = []

    for tool in available_tools:
        tool_type = classify_tool_type(tool)
        if tool_type == CtfToolType.SHELL:
            shell_tools.append(tool)
        elif tool_type == CtfToolType.PYTHON:
            python_tools.append(tool)
        else:
            other_tools.append(tool)

    # Python first (for enumeration/crypto), then Shell (for quick commands), then others
    return python_tools + shell_tools + other_tools


def should_require_confirmation(risk_level: CtfRiskLevel) -> bool:
    """Check if action requires user confirmation based on risk level."""
    return risk_level in (CtfRiskLevel.MEDIUM, CtfRiskLevel.HIGH)
