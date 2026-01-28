#!/usr/bin/env python3
"""
CVE Intelligence (Orchestrator)

This module preserves the public import surface:
- CVEIntelligenceManager
- cve_intelligence

Implementation details live in:
- fetcher.py
- analyzer.py
- exploits.py
"""

from .analyzer import analyze_cve_exploitability as _analyze_cve_exploitability
from .exploits import search_existing_exploits as _search_existing_exploits
from .fetcher import fetch_latest_cves as _fetch_latest_cves


class CVEIntelligenceManager:
    """Advanced CVE Intelligence and Vulnerability Management System"""

    def __init__(self):
        self.cve_cache = {}
        self.vulnerability_db = {}
        self.threat_intelligence = {}

    def fetch_latest_cves(self, hours=24, severity_filter="HIGH,CRITICAL"):
        """Fetch latest CVEs from NVD and other real sources."""
        return _fetch_latest_cves(hours=hours, severity_filter=severity_filter)

    def analyze_cve_exploitability(self, cve_id):
        """Analyze CVE exploitability using real CVE data and threat intelligence."""
        return _analyze_cve_exploitability(cve_id)

    def search_existing_exploits(self, cve_id):
        """Search for existing exploits from real sources."""
        return _search_existing_exploits(cve_id)


# todo: implement optimization, directly expose atomic capabilities
cve_intelligence = CVEIntelligenceManager()
