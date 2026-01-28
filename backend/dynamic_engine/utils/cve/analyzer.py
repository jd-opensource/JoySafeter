import logging
import re
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _sanitize_log_message(message: str) -> str:
    """
    Sanitize log messages to prevent log forgery attacks.

    Removes control characters (except \\n and \\t) and ANSI escape sequences.

    Args:
        message: The message to sanitize

    Returns:
        Sanitized message safe for logging
    """
    # Remove control characters (except newline \n and tab \t) - including \r\x0d
    cleaned = re.sub(r"[\x00-\x08\x0b-\x0d\x0e-\x1f\x7f-\x9f]", "", message)
    # Remove ANSI CSI escape sequences (like \x1b[31m)
    cleaned = re.sub(r"\x1b\[[0-9;]*m?", "", cleaned)
    # Remove any remaining brackets that were part of ANSI sequences
    cleaned = re.sub(r"\[[0-9;]*m?", "", cleaned)
    # Also remove OSC sequences
    cleaned = re.sub(r"\x1b\][^\x07\x1b]*[\x07\x1b\\]", "", cleaned)
    return cleaned


def analyze_cve_exploitability(cve_id: str) -> dict[str, Any]:
    """Analyze CVE exploitability using real CVE data and threat intelligence."""
    try:
        logger.info(f"🔬 Analyzing exploitability for {_sanitize_log_message(cve_id)}")

        # Fetch detailed CVE data from NVD
        nvd_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"
        params = {"cveId": cve_id}

        try:
            response = requests.get(nvd_url, params=params, timeout=30)

            if response.status_code != 200:
                logger.warning(_sanitize_log_message(f"⚠️ NVD API returned status {response.status_code} for {cve_id}"))
                return {
                    "success": False,
                    "error": f"Failed to fetch CVE data: HTTP {response.status_code}",
                    "cve_id": cve_id,
                }

            nvd_data = response.json()
            vulnerabilities = nvd_data.get("vulnerabilities", [])

            if not vulnerabilities:
                logger.warning(f"⚠️ No data found for CVE {cve_id}")
                return {"success": False, "error": f"CVE {cve_id} not found in NVD database", "cve_id": cve_id}

            cve_data = vulnerabilities[0].get("cve", {})

            # Extract CVSS metrics for exploitability analysis
            metrics = cve_data.get("metrics", {})
            cvss_score = 0.0
            severity = "UNKNOWN"
            attack_vector = "UNKNOWN"
            attack_complexity = "UNKNOWN"
            privileges_required = "UNKNOWN"
            user_interaction = "UNKNOWN"
            exploitability_subscore = 0.0

            # Analyze CVSS v3.1 metrics (preferred)
            if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                cvss_data = metrics["cvssMetricV31"][0]["cvssData"]
                cvss_score = cvss_data.get("baseScore", 0.0)
                severity = cvss_data.get("baseSeverity", "UNKNOWN").upper()
                attack_vector = cvss_data.get("attackVector", "UNKNOWN")
                attack_complexity = cvss_data.get("attackComplexity", "UNKNOWN")
                privileges_required = cvss_data.get("privilegesRequired", "UNKNOWN")
                user_interaction = cvss_data.get("userInteraction", "UNKNOWN")
                exploitability_subscore = cvss_data.get("exploitabilityScore", 0.0)

            elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
                cvss_data = metrics["cvssMetricV30"][0]["cvssData"]
                cvss_score = cvss_data.get("baseScore", 0.0)
                severity = cvss_data.get("baseSeverity", "UNKNOWN").upper()
                attack_vector = cvss_data.get("attackVector", "UNKNOWN")
                attack_complexity = cvss_data.get("attackComplexity", "UNKNOWN")
                privileges_required = cvss_data.get("privilegesRequired", "UNKNOWN")
                user_interaction = cvss_data.get("userInteraction", "UNKNOWN")
                exploitability_subscore = cvss_data.get("exploitabilityScore", 0.0)

            # Calculate exploitability score based on CVSS metrics
            exploitability_score = 0.0

            # Base exploitability on CVSS exploitability subscore if available
            if exploitability_subscore > 0:
                exploitability_score = min(exploitability_subscore / 3.9, 1.0)  # Normalize to 0-1
            else:
                # Calculate based on individual CVSS components
                score_components = 0.0

                # Attack Vector scoring
                if attack_vector == "NETWORK":
                    score_components += 0.4
                elif attack_vector == "ADJACENT_NETWORK":
                    score_components += 0.3
                elif attack_vector == "LOCAL":
                    score_components += 0.2
                elif attack_vector == "PHYSICAL":
                    score_components += 0.1

                # Attack Complexity scoring
                if attack_complexity == "LOW":
                    score_components += 0.3
                elif attack_complexity == "HIGH":
                    score_components += 0.1

                # Privileges Required scoring
                if privileges_required == "NONE":
                    score_components += 0.2
                elif privileges_required == "LOW":
                    score_components += 0.1

                # User Interaction scoring
                if user_interaction == "NONE":
                    score_components += 0.1

                exploitability_score = min(score_components, 1.0)

            # Determine exploitability level
            if exploitability_score >= 0.8:
                exploitability_level = "HIGH"
            elif exploitability_score >= 0.6:
                exploitability_level = "MEDIUM"
            elif exploitability_score >= 0.3:
                exploitability_level = "LOW"
            else:
                exploitability_level = "VERY_LOW"

            # Extract description for additional context
            descriptions = cve_data.get("descriptions", [])
            description = ""
            for desc in descriptions:
                if desc.get("lang") == "en":
                    description = desc.get("value", "")
                    break

            # Analyze description for exploit indicators
            exploit_keywords = [
                "remote code execution",
                "rce",
                "buffer overflow",
                "stack overflow",
                "heap overflow",
                "use after free",
                "double free",
                "format string",
                "sql injection",
                "command injection",
                "authentication bypass",
                "privilege escalation",
                "directory traversal",
                "path traversal",
                "deserialization",
                "xxe",
                "ssrf",
                "csrf",
                "xss",
            ]

            description_lower = description.lower()
            exploit_indicators = [kw for kw in exploit_keywords if kw in description_lower]

            # Adjust exploitability based on vulnerability type
            if any(kw in description_lower for kw in ["remote code execution", "rce", "buffer overflow"]):
                exploitability_score = min(exploitability_score + 0.2, 1.0)
            elif any(kw in description_lower for kw in ["authentication bypass", "privilege escalation"]):
                exploitability_score = min(exploitability_score + 0.15, 1.0)

            # Check for public exploit availability indicators
            public_exploits = False
            exploit_maturity = "UNKNOWN"

            # Look for exploit references in CVE references
            references = cve_data.get("references", [])
            exploit_sources = ["exploit-db.com", "github.com", "packetstormsecurity.com", "metasploit"]

            for ref in references:
                ref_url = ref.get("url", "").lower()
                if any(source in ref_url for source in exploit_sources):
                    public_exploits = True
                    exploit_maturity = "PROOF_OF_CONCEPT"
                    break

            # Determine weaponization level
            weaponization_level = "LOW"
            if public_exploits and exploitability_score > 0.7:
                weaponization_level = "HIGH"
            elif public_exploits and exploitability_score > 0.5 or exploitability_score > 0.8:
                weaponization_level = "MEDIUM"

            # Active exploitation assessment
            active_exploitation = False
            if (
                exploitability_score > 0.8
                and public_exploits
                or severity in ["CRITICAL", "HIGH"]
                and attack_vector == "NETWORK"
            ):
                active_exploitation = True

            # Priority recommendation
            if exploitability_score > 0.8 and severity == "CRITICAL":
                priority = "IMMEDIATE"
            elif exploitability_score > 0.7 or severity == "CRITICAL":
                priority = "HIGH"
            elif exploitability_score > 0.5 or severity == "HIGH":
                priority = "MEDIUM"
            else:
                priority = "LOW"

            # Extract publication and modification dates
            published_date = cve_data.get("published", "")
            last_modified = cve_data.get("lastModified", "")

            analysis = {
                "success": True,
                "cve_id": cve_id,
                "exploitability_score": round(exploitability_score, 2),
                "exploitability_level": exploitability_level,
                "cvss_score": cvss_score,
                "severity": severity,
                "attack_vector": attack_vector,
                "attack_complexity": attack_complexity,
                "privileges_required": privileges_required,
                "user_interaction": user_interaction,
                "exploitability_subscore": exploitability_subscore,
                "exploit_availability": {
                    "public_exploits": public_exploits,
                    "exploit_maturity": exploit_maturity,
                    "weaponization_level": weaponization_level,
                },
                "threat_intelligence": {
                    "active_exploitation": active_exploitation,
                    "exploit_prediction": f"{exploitability_score * 100:.1f}% likelihood of exploitation",
                    "recommended_priority": priority,
                    "exploit_indicators": exploit_indicators,
                },
                "vulnerability_details": {
                    "description": description[:500] + "..." if len(description) > 500 else description,
                    "published_date": published_date,
                    "last_modified": last_modified,
                    "references_count": len(references),
                },
                "data_source": "NVD API v2.0",
                "analysis_timestamp": datetime.now().isoformat(),
            }

            logger.info(
                _sanitize_log_message(
                    f"✅ Completed exploitability analysis for {cve_id}: {exploitability_level} ({exploitability_score:.2f})"
                )
            )

            return analysis

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Network error analyzing {cve_id}: {str(e)}")
            return {"success": False, "error": f"Network error: {str(e)}", "cve_id": cve_id}

    except Exception as e:
        logger.error(f"💥 Error analyzing CVE {cve_id}: {str(e)}")
        return {"success": False, "error": str(e), "cve_id": cve_id}
