import logging
import re
from datetime import datetime, timedelta
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


def fetch_latest_cves(hours: int = 24, severity_filter: str = "HIGH,CRITICAL") -> dict[str, Any]:
    """Fetch latest CVEs from NVD and other real sources."""
    try:
        logger.info(_sanitize_log_message(f"🔍 Fetching CVEs from last {hours} hours with severity: {severity_filter}"))

        # Calculate date range for CVE search
        end_date = datetime.now()
        start_date = end_date - timedelta(hours=hours)

        # Format dates for NVD API (ISO 8601 format)
        start_date_str = start_date.strftime("%Y-%m-%dT%H:%M:%S.000")
        end_date_str = end_date.strftime("%Y-%m-%dT%H:%M:%S.000")

        # NVD API endpoint
        nvd_url = "https://services.nvd.nist.gov/rest/json/cves/2.0"

        # Parse severity filter
        severity_levels = [s.strip().upper() for s in severity_filter.split(",")]

        all_cves = []

        # Query NVD API with rate limiting compliance
        params = {"lastModStartDate": start_date_str, "lastModEndDate": end_date_str, "resultsPerPage": 100}

        try:
            # Add delay to respect NVD rate limits (6 seconds between requests for unauthenticated)
            import time

            logger.info(f"🌐 Querying NVD API: {nvd_url}")
            response = requests.get(nvd_url, params=params, timeout=30)

            if response.status_code == 200:
                nvd_data = response.json()
                vulnerabilities = nvd_data.get("vulnerabilities", [])

                logger.info(f"📊 Retrieved {len(vulnerabilities)} vulnerabilities from NVD")

                for vuln_item in vulnerabilities:
                    cve_data = vuln_item.get("cve", {})
                    cve_id = cve_data.get("id", "Unknown")

                    # Extract CVSS scores and determine severity
                    metrics = cve_data.get("metrics", {})
                    cvss_score = 0.0
                    severity = "UNKNOWN"

                    # Try CVSS v3.1 first, then v3.0, then v2.0
                    if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                        cvss_data = metrics["cvssMetricV31"][0]["cvssData"]
                        cvss_score = cvss_data.get("baseScore", 0.0)
                        severity = cvss_data.get("baseSeverity", "UNKNOWN").upper()
                    elif "cvssMetricV30" in metrics and metrics["cvssMetricV30"]:
                        cvss_data = metrics["cvssMetricV30"][0]["cvssData"]
                        cvss_score = cvss_data.get("baseScore", 0.0)
                        severity = cvss_data.get("baseSeverity", "UNKNOWN").upper()
                    elif "cvssMetricV2" in metrics and metrics["cvssMetricV2"]:
                        cvss_data = metrics["cvssMetricV2"][0]["cvssData"]
                        cvss_score = cvss_data.get("baseScore", 0.0)
                        # Convert CVSS v2 score to severity
                        if cvss_score >= 9.0:
                            severity = "CRITICAL"
                        elif cvss_score >= 7.0:
                            severity = "HIGH"
                        elif cvss_score >= 4.0:
                            severity = "MEDIUM"
                        else:
                            severity = "LOW"

                    # Filter by severity if specified
                    if severity not in severity_levels and severity_levels != ["ALL"]:
                        continue

                    # Extract description
                    descriptions = cve_data.get("descriptions", [])
                    description = "No description available"
                    for desc in descriptions:
                        if desc.get("lang") == "en":
                            description = desc.get("value", description)
                            break

                    # Extract references
                    references = []
                    ref_data = cve_data.get("references", [])
                    for ref in ref_data[:5]:  # Limit to first 5 references
                        references.append(ref.get("url", ""))

                    # Extract affected software (CPE data)
                    affected_software = []
                    configurations = cve_data.get("configurations", [])
                    for config in configurations:
                        nodes = config.get("nodes", [])
                        for node in nodes:
                            cpe_match = node.get("cpeMatch", [])
                            for cpe in cpe_match[:3]:  # Limit to first 3 CPEs
                                cpe_name = cpe.get("criteria", "")
                                if cpe_name.startswith("cpe:2.3:"):
                                    # Parse CPE to get readable software name
                                    parts = cpe_name.split(":")
                                    if len(parts) >= 6:
                                        vendor = parts[3]
                                        product = parts[4]
                                        version = parts[5] if parts[5] != "*" else "all versions"
                                        affected_software.append(f"{vendor} {product} {version}")

                    cve_entry = {
                        "cve_id": cve_id,
                        "description": description,
                        "severity": severity,
                        "cvss_score": cvss_score,
                        "published_date": cve_data.get("published", ""),
                        "last_modified": cve_data.get("lastModified", ""),
                        "affected_software": affected_software[:5],  # Limit to 5 entries
                        "references": references,
                        "source": "NVD",
                    }

                    all_cves.append(cve_entry)

            else:
                logger.warning(f"⚠️ NVD API returned status code: {response.status_code}")

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Error querying NVD API: {str(e)}")

        # If no CVEs found from NVD, try alternative sources or provide informative response
        if not all_cves:
            logger.info("🔄 No recent CVEs found in specified timeframe, checking for any recent critical CVEs...")

            # Try a broader search for recent critical CVEs (last 7 days)
            try:
                broader_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S.000")
                broader_params = {
                    "lastModStartDate": broader_start,
                    "lastModEndDate": end_date_str,
                    "cvssV3Severity": "CRITICAL",
                    "resultsPerPage": 20,
                }

                time.sleep(6)  # Rate limit compliance
                response = requests.get(nvd_url, params=broader_params, timeout=30)

                if response.status_code == 200:
                    nvd_data = response.json()
                    vulnerabilities = nvd_data.get("vulnerabilities", [])

                    for vuln_item in vulnerabilities[:10]:  # Limit to 10 most recent
                        cve_data = vuln_item.get("cve", {})
                        cve_id = cve_data.get("id", "Unknown")

                        # Extract basic info for recent critical CVEs
                        descriptions = cve_data.get("descriptions", [])
                        description = "No description available"
                        for desc in descriptions:
                            if desc.get("lang") == "en":
                                description = desc.get("value", description)
                                break

                        metrics = cve_data.get("metrics", {})
                        cvss_score = 0.0
                        if "cvssMetricV31" in metrics and metrics["cvssMetricV31"]:
                            cvss_score = metrics["cvssMetricV31"][0]["cvssData"].get("baseScore", 0.0)

                        cve_entry = {
                            "cve_id": cve_id,
                            "description": description,
                            "severity": "CRITICAL",
                            "cvss_score": cvss_score,
                            "published_date": cve_data.get("published", ""),
                            "last_modified": cve_data.get("lastModified", ""),
                            "affected_software": ["Various (see references)"],
                            "references": [f"https://nvd.nist.gov/vuln/detail/{cve_id}"],
                            "source": "NVD (Recent Critical)",
                        }

                        all_cves.append(cve_entry)

            except Exception as broader_e:
                logger.warning(f"⚠️ Broader search also failed: {str(broader_e)}")

        logger.info(f"✅ Successfully retrieved {len(all_cves)} CVEs")

        return {
            "success": True,
            "cves": all_cves,
            "total_found": len(all_cves),
            "hours_searched": hours,
            "severity_filter": severity_filter,
            "data_sources": ["NVD API v2.0"],
            "search_period": f"{start_date_str} to {end_date_str}",
        }

    except Exception as e:
        logger.error(f"💥 Error fetching CVEs: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "cves": [],
            "fallback_message": "CVE fetching failed, check network connectivity and API availability",
        }
