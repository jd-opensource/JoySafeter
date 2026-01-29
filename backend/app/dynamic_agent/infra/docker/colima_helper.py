"""
Colima environment detection and initialization helper
"""

import os
import subprocess
from typing import Any, Dict, Optional, Tuple

from loguru import logger


class ColimaHelper:
    """Helper class for Colima Docker environment management"""

    # Colima socket path
    COLIMA_SOCKET = os.path.expanduser("~/.colima/docker.sock")
    COLIMA_CONFIG = os.path.expanduser("~/.colima/colima.yaml")

    @staticmethod
    def is_colima_installed() -> bool:
        """Check if Colima is installed"""
        try:
            result = subprocess.run(["colima", "--version"], capture_output=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    @staticmethod
    def is_colima_running() -> bool:
        """Check if Colima VM is running"""
        try:
            result = subprocess.run(["colima", "status"], capture_output=True, timeout=5)
            return result.returncode == 0 and b"running" in result.stdout.lower()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    @staticmethod
    def get_docker_socket() -> str:
        """Get Docker socket path (Colima or default)"""
        if os.path.exists(ColimaHelper.COLIMA_SOCKET):
            return ColimaHelper.COLIMA_SOCKET
        return "/var/run/docker.sock"

    @staticmethod
    def get_colima_status() -> Dict[str, str | bool]:
        """Get detailed Colima status"""
        try:
            result = subprocess.run(["colima", "status"], capture_output=True, text=True, timeout=5)

            status: Dict[str, str | bool] = {
                "installed": True,
                "running": result.returncode == 0,
                "output": result.stdout.strip(),
            }

            # Parse status output
            if "running" in result.stdout.lower():
                status["state"] = "running"
            elif "stopped" in result.stdout.lower():
                status["state"] = "stopped"
            else:
                status["state"] = "unknown"

            return status
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"installed": False, "running": False, "state": "not_installed", "output": "Colima not installed"}

    @staticmethod
    def start_colima(cpu: int = 4, memory: int = 8, disk: int = 100) -> Tuple[bool, str]:
        """
        Start Colima with specified resources

        Args:
            cpu: Number of CPU cores
            memory: Memory in GB
            disk: Disk in GB

        Returns:
            Tuple of (success, message)
        """
        # ============ Security: Parameter validation to prevent command injection ============
        try:
            cpu_int = int(cpu)
            memory_int = int(memory)
            disk_int = int(disk)

            # Reasonable range checks
            if not (1 <= cpu_int <= 64):
                raise ValueError(f"CPU count {cpu_int} out of range [1, 64]")
            if not (1 <= memory_int <= 128):
                raise ValueError(f"Memory {memory_int}GB out of range [1, 128]")
            if not (10 <= disk_int <= 1000):
                raise ValueError(f"Disk {disk_int}GB out of range [10, 1000]")
        except (ValueError, TypeError) as e:
            return False, f"Invalid parameters: {e}"

        try:
            # Check if already running
            if ColimaHelper.is_colima_running():
                return True, "Colima is already running"

            # Start Colima with validated parameters
            cmd = ["colima", "start", "--cpu", str(cpu_int), "--memory", str(memory_int), "--disk", str(disk_int)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return True, f"Colima started successfully with {cpu_int} CPU, {memory_int}GB memory, {disk_int}GB disk"
            else:
                return False, f"Failed to start Colima: {result.stderr}"

        except subprocess.TimeoutExpired:
            return False, "Colima startup timeout"
        except FileNotFoundError:
            return False, "Colima not installed. Install with: brew install colima"
        except Exception as e:
            return False, f"Error starting Colima: {str(e)}"

    @staticmethod
    def stop_colima() -> Tuple[bool, str]:
        """Stop Colima VM"""
        try:
            result = subprocess.run(["colima", "stop"], capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return True, "Colima stopped successfully"
            else:
                return False, f"Failed to stop Colima: {result.stderr}"

        except subprocess.TimeoutExpired:
            return False, "Colima stop timeout"
        except FileNotFoundError:
            return False, "Colima not installed"
        except Exception as e:
            return False, f"Error stopping Colima: {str(e)}"

    @staticmethod
    def setup_environment() -> Tuple[bool, str]:
        """
        Setup Docker environment for Colima

        Returns:
            Tuple of (success, message)
        """
        try:
            # Check if Colima is installed
            if not ColimaHelper.is_colima_installed():
                return False, "Colima not installed. Install with: brew install colima"

            # Check if Colima is running
            if not ColimaHelper.is_colima_running():
                success, msg = ColimaHelper.start_colima()
                if not success:
                    return False, msg

            # Set Docker environment variable
            docker_socket = ColimaHelper.get_docker_socket()
            os.environ["DOCKER_HOST"] = f"unix://{docker_socket}"

            # Verify Docker connection
            try:
                result = subprocess.run(["docker", "ps"], capture_output=True, timeout=5)

                if result.returncode == 0:
                    return True, "Colima environment setup successful"
                else:
                    return False, "Docker connection failed"

            except subprocess.TimeoutExpired:
                return False, "Docker connection timeout"

        except Exception as e:
            return False, f"Error setting up Colima environment: {str(e)}"

    @staticmethod
    def get_docker_info() -> Optional[Dict[Any, Any]]:
        """Get Docker info from Colima"""
        try:
            result = subprocess.run(["docker", "info", "--format=json"], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                import json

                return json.loads(result.stdout)  # type: ignore[no-any-return]

            return None
        except (json.JSONDecodeError, subprocess.SubprocessError) as e:
            logger.debug(f"Failed to get Colima status: {e}")
            return None

    @staticmethod
    def get_colima_resources() -> Optional[Dict[str, str]]:
        """Get Colima VM resource information"""
        try:
            # Get CPU info
            cpu_result = subprocess.run(["colima", "ssh", "--", "nproc"], capture_output=True, text=True, timeout=5)

            # Get memory info
            mem_result = subprocess.run(
                ["colima", "ssh", "--", "free", "-h"], capture_output=True, text=True, timeout=5
            )

            # Get disk info
            disk_result = subprocess.run(
                ["colima", "ssh", "--", "df", "-h", "/"], capture_output=True, text=True, timeout=5
            )

            resources = {}

            if cpu_result.returncode == 0:
                resources["cpu_cores"] = cpu_result.stdout.strip()

            if mem_result.returncode == 0:
                resources["memory"] = mem_result.stdout.strip()

            if disk_result.returncode == 0:
                resources["disk"] = disk_result.stdout.strip()

            return resources if resources else None

        except subprocess.SubprocessError as e:
            logger.debug(f"Failed to get Colima resources: {e}")
            return None

    @staticmethod
    def print_status():
        """Print Colima and Docker status"""
        logger.debug("\n" + "=" * 60)
        logger.debug("Colima & Docker Environment Status")
        logger.debug("=" * 60)

        # Colima status
        colima_status = ColimaHelper.get_colima_status()
        logger.debug("\n🔧 Colima:")
        logger.debug(f"   Installed: {'✅ Yes' if colima_status['installed'] else '❌ No'}")
        logger.debug(f"   Running: {'✅ Yes' if colima_status['running'] else '❌ No'}")
        logger.debug(f"   State: {colima_status['state']}")

        # Docker socket
        docker_socket = ColimaHelper.get_docker_socket()
        socket_exists = os.path.exists(docker_socket)
        logger.debug("\n🐳 Docker:")
        logger.debug(f"   Socket: {docker_socket}")
        logger.debug(f"   Available: {'✅ Yes' if socket_exists else '❌ No'}")

        # Docker info
        docker_info = ColimaHelper.get_docker_info()
        if docker_info:
            logger.debug(f"   Version: {docker_info.get('ServerVersion', 'Unknown')}")
            logger.debug(f"   OS: {docker_info.get('OperatingSystem', 'Unknown')}")
            logger.debug(f"   Containers: {docker_info.get('Containers', 'Unknown')}")
            logger.debug(f"   Images: {docker_info.get('Images', 'Unknown')}")

        # Colima resources
        resources = ColimaHelper.get_colima_resources()
        if resources:
            logger.debug("\n📊 Colima Resources:")
            if "cpu_cores" in resources:
                logger.debug(f"   CPU Cores: {resources['cpu_cores']}")
            if "logger.debug" in resources:
                logger.debug(f"   Memory:\n{resources['memory']}")
            if "disk" in resources:
                logger.debug(f"   Disk:\n{resources['disk']}")

        logger.debug("\n" + "=" * 60 + "\n")


def main():
    """Main function for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Colima Helper")
    parser.add_argument("command", choices=["status", "start", "stop", "setup"], help="Command to execute")
    parser.add_argument("--cpu", type=int, default=4, help="CPU cores (for start)")
    parser.add_argument("--memory", type=int, default=8, help="Memory in GB (for start)")
    parser.add_argument("--disk", type=int, default=100, help="Disk in GB (for start)")

    args = parser.parse_args()

    if args.command == "status":
        ColimaHelper.print_status()

    elif args.command == "start":
        print(f"Starting Colima with {args.cpu} CPU, {args.memory}GB memory, {args.disk}GB disk...")
        success, msg = ColimaHelper.start_colima(args.cpu, args.memory, args.disk)
        print(f"{'✅' if success else '❌'} {msg}")
        if success:
            ColimaHelper.print_status()

    elif args.command == "stop":
        print("Stopping Colima...")
        success, msg = ColimaHelper.stop_colima()
        print(f"{'✅' if success else '❌'} {msg}")

    elif args.command == "setup":
        print("Setting up Colima environment...")
        success, msg = ColimaHelper.setup_environment()
        print(f"{'✅' if success else '❌'} {msg}")
        if success:
            ColimaHelper.print_status()


if __name__ == "__main__":
    main()
