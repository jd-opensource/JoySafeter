"""
Colima initialization and Docker manager setup for the project
"""

import sys
from typing import Optional

from app.dynamic_agent.infra.docker.docker_manager import DockerManager
from app.dynamic_agent.infra.docker.resource_limiter import ResourceLimits


class ColimaDockerSetup:
    """Setup Docker environment with Colima for the project"""

    def __init__(self, auto_start: bool = True):
        """
        Initialize Colima Docker setup

        Args:
            auto_start: Automatically start Colima if not running
        """
        self.auto_start = auto_start
        self.manager: Optional[DockerManager] = None

    def initialize(self) -> bool:
        success = DockerManager.initialize_colima()
        if not success:
            return False
        self.manager = DockerManager()
        return success

    def get_manager(self) -> Optional[DockerManager]:
        """Get initialized DockerManager instance"""
        return self.manager

    def create_container(
        self,
        image: str,
        command: str,
        cpu: str = "2",
        memory: str = "4G",
        disk: str = "20G",
        name: Optional[str] = None,
        auto_remove: bool = False,
    ):
        """
        Create a Kali container with resource limits

        Args:
            cpu: CPU cores (e.g., "2")
            memory: Memory (e.g., "4G")
            disk: Disk (e.g., "20G")
            name: Container name (optional)

        Returns:
            Container object or None if failed
        """
        if not self.manager:
            print("❌ Docker manager not initialized")
            return None

        try:
            # Create resource limits
            limits = ResourceLimits.from_human_readable(cpu=cpu, memory=memory, disk=disk)

            # Create container
            container = self.manager.create_container(
                image=image,
                command=command,
                resource_limits=limits,
                name=name,
                auto_remove=auto_remove,
            )

            print(f"✅ Kali container created: {container.id[:12]}")
            return container

        except Exception as e:
            print(f"❌ Failed to create container: {e}")
            return None

    def cleanup(self):
        """Cleanup resources"""
        if self.manager:
            # Stop all containers
            try:
                containers = self.manager.client.containers.list()
                for container in containers:
                    print(f"Stopping container {container.id[:12]}...")
                    self.manager.stop_container(container.id)
                    self.manager.remove_container(container.id)
            except Exception as e:
                print(f"Error during cleanup: {e}")


def main():
    """Main function for testing"""
    import argparse

    parser = argparse.ArgumentParser(description="Colima Docker Setup")
    parser.add_argument("--no-auto-start", action="store_true", help="Do not auto-start Colima")
    parser.add_argument("--test", action="store_true", help="Run test with Kali container")

    args = parser.parse_args()

    # Initialize setup
    setup = ColimaDockerSetup(auto_start=not args.no_auto_start)

    if not setup.initialize():
        print("❌ Initialization failed")
        sys.exit(1)

    # Test with Kali container if requested
    # if args.test:
    if True:
        print("\n" + "=" * 70)
        print("Testing with Kali Container")
        print("=" * 70 + "\n")

        auto_remove = True
        container = setup.create_container(
            "seclens-dev:0",
            "sleep 10",
            cpu="1",
            memory="2G",
            disk="10G",
            name="test-kali",
            auto_remove=auto_remove,
        )

        if container:
            manager = setup.get_manager()

            # Execute test command
            print("\n📋 Executing test command...")
            exit_code, stdout, stderr = manager.execute_command(container.id, 'echo "Kali container is working!"')

            if exit_code == 0:
                print("✅ Test successful")
                print(f"Output: {stdout}")
            else:
                print(f"❌ Test failed: {stderr}")

            if not auto_remove:
                # Cleanup
                print("\n📋 Cleaning up...")
                manager.stop_container(container.id)

                manager.remove_container(container.id)
                print("✅ Cleanup complete")

    print("\n✅ Setup complete!")


if __name__ == "__main__":
    main()
