"""
CLI interface for the whitebox scanner

Usage:
    python -m agent.core.scanner.cli scan <path_to_zip>
    python -m agent.core.scanner.cli --help
"""

import argparse
import json
import sys
from pathlib import Path

from .manager import ScannerManager


def cmd_scan(args):
    """
    Execute a scan command.

    Args:
        args: Parsed arguments
    """
    zip_path = args.zip_path
    output_file = args.output

    # Validate input
    if not Path(zip_path).exists():
        print(f"Error: File {zip_path} does not exist")
        sys.exit(1)

    # Run scan
    print(f"Starting scan of {zip_path}...")
    manager = ScannerManager()

    try:
        result = manager.run_scan(zip_path)

        # Print summary
        print("\n" + "=" * 60)
        print("SCAN RESULTS")
        print("=" * 60)
        print(f"Scan ID: {result['scan_id']}")
        print(f"Files scanned: {result['scanned_files']}")
        print(f"Duration: {result['scan_duration_ms']}ms")
        print("\nFindings Summary:")
        print(f"  Total: {result['summary']['total']}")
        print(f"  High: {result['summary']['high']}")
        print(f"  Medium: {result['summary']['medium']}")
        print(f"  Low: {result['summary']['low']}")
        print(f"  Info: {result['summary']['info']}")

        # Print findings
        if result["findings"]:
            print("\n" + "=" * 60)
            print("DETAILED FINDINGS")
            print("=" * 60)

            for i, finding in enumerate(result["findings"], 1):
                print(f"\n[{i}] {finding['type']}")
                print(f"    Severity: {finding['severity']}")
                print(f"    File: {finding['file_path']}")
                print(f"    Line: {finding['line_number']}")
                print(f"    Code: {finding['code_snippet'][:80]}...")
                print(f"    Agent: {finding['agent_verification']}")
                if finding["agent_comment"]:
                    print(f"    Comment: {finding['agent_comment']}")
        else:
            print("\nNo vulnerabilities found!")

        # Save to file if specified
        if output_file:
            with open(output_file, "w") as f:
                json.dump(result, f, indent=2)
            print(f"\nResults saved to {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Whitebox Scanner - Static Analysis for Vulnerabilities",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s scan /path/to/code.zip
  %(prog)s scan /path/to/code.zip --output results.json
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Scan command
    scan_parser = subparsers.add_parser("scan", help="Scan a ZIP file for vulnerabilities")
    scan_parser.add_argument("zip_path", help="Path to ZIP file containing source code")
    scan_parser.add_argument("-o", "--output", help="Output file for JSON results (optional)")
    scan_parser.set_defaults(func=cmd_scan)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Execute command
    args.func(args)


if __name__ == "__main__":
    main()
