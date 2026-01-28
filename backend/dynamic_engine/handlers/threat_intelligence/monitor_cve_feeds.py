import logging
from datetime import datetime
from typing import Any, Dict

from dynamic_engine.mcp.handler import AbstractHandler, HandlerType
from dynamic_engine.utils.cve.intelligence import cve_intelligence

logger = logging.getLogger(__name__)


class CveMonitorHandler(AbstractHandler):
    """Handler for cve_monitor functionality"""

    def type(self) -> HandlerType:
        return HandlerType.PYTHON

    def commands(self) -> list:
        """Handler related commands"""
        return []

    def handle(self, data: Dict) -> Any:
        """Execute cve_monitor with enhanced logging"""
        try:
            hours = data.get("hours", 24)
            severity_filter = data.get("severity_filter", "HIGH,CRITICAL")
            keywords = data.get("keywords", "")
            logger.info(f"🔍 Monitoring CVE feeds for last {hours} hours with severity filter: {severity_filter}")
            cve_results = cve_intelligence.fetch_latest_cves(hours, severity_filter)
            if keywords and cve_results.get("success"):
                keyword_list = [k.strip().lower() for k in keywords.split(",")]
                filtered_cves = []
                for cve in cve_results.get("cves", []):
                    description = cve.get("description", "").lower()
                    if any(keyword in description for keyword in keyword_list):
                        filtered_cves.append(cve)
                cve_results["cves"] = filtered_cves
                cve_results["filtered_by_keywords"] = keywords
                cve_results["total_after_filter"] = len(filtered_cves)
            exploitability_analysis = []
            for cve in cve_results.get("cves", [])[:5]:
                cve_id = cve.get("cve_id", "")
                if cve_id:
                    analysis = cve_intelligence.analyze_cve_exploitability(cve_id)
                    if analysis.get("success"):
                        exploitability_analysis.append(analysis)
            result = {
                "success": True,
                "cve_monitoring": cve_results,
                "exploitability_analysis": exploitability_analysis,
                "timestamp": datetime.now().isoformat(),
            }
            logger.info(f"📊 CVE monitoring completed | Found: {len(cve_results.get('cves', []))} CVEs")
            return result
        except Exception as e:
            logger.error(f"💥 Error in CVE monitoring: {str(e)}")
            return {"success": False, "error": f"Server error: {str(e)}"}
