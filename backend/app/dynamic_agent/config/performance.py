"""
Performance Configuration and Optimization Settings

This module provides configuration for database connection pooling,
query caching, and performance monitoring.
"""

from loguru import logger


class DatabasePoolConfig:
    """Database connection pool configuration."""

    # Connection pool size
    POOL_SIZE = 20

    # Maximum overflow connections
    MAX_OVERFLOW = 40

    # Connection timeout (seconds)
    CONNECT_TIMEOUT = 10

    # Idle connection timeout (seconds)
    POOL_RECYCLE = 3600

    # Enable connection pre-ping to detect stale connections
    POOL_PRE_PING = True

    # Echo SQL statements (disable in production)
    ECHO_SQL = False

    @classmethod
    def get_sqlalchemy_config(cls) -> dict:
        """Get SQLAlchemy engine configuration.

        Returns:
            Dictionary of engine configuration options
        """
        return {
            "pool_size": cls.POOL_SIZE,
            "max_overflow": cls.MAX_OVERFLOW,
            "connect_args": {
                "timeout": cls.CONNECT_TIMEOUT,
            },
            "pool_recycle": cls.POOL_RECYCLE,
            "pool_pre_ping": cls.POOL_PRE_PING,
            "echo": cls.ECHO_SQL,
        }


class QueryCacheConfig:
    """Query caching configuration."""

    # Enable query caching
    ENABLED = True

    # Cache TTL in seconds
    TTL_SECONDS = 300  # 5 minutes

    # Maximum cache size (number of entries)
    MAX_ENTRIES = 1000

    # Cache key prefix
    KEY_PREFIX = "task_tracking:"

    @classmethod
    def get_cache_key(cls, entity_type: str, entity_id: str) -> str:
        """Generate cache key for an entity.

        Args:
            entity_type: Type of entity (task, step, etc.)
            entity_id: ID of the entity

        Returns:
            Cache key string
        """
        return f"{cls.KEY_PREFIX}{entity_type}:{entity_id}"


class PerformanceMonitoringConfig:
    """Performance monitoring configuration."""

    # Enable performance monitoring
    ENABLED = True

    # Log slow queries (milliseconds)
    SLOW_QUERY_THRESHOLD_MS = 1000

    # Log slow API endpoints (milliseconds)
    SLOW_ENDPOINT_THRESHOLD_MS = 500

    # Metrics collection interval (seconds)
    METRICS_INTERVAL_SECONDS = 60

    # Enable detailed metrics
    DETAILED_METRICS = False


class TreeRenderingConfig:
    """Tree rendering optimization configuration."""

    # Enable tree virtualization
    VIRTUALIZATION_ENABLED = True

    # Maximum nodes to render without virtualization
    VIRTUALIZATION_THRESHOLD = 100

    # Lazy load children on expand
    LAZY_LOAD_CHILDREN = True

    # Maximum depth to load initially
    INITIAL_DEPTH = 2

    # Batch size for loading children
    BATCH_SIZE = 50


class FeatureFlagConfig:
    """Feature flag configuration."""

    # Enable task tracking feature
    TASK_TRACKING_ENABLED = True

    # Enable real-time updates
    REAL_TIME_UPDATES_ENABLED = True

    # Enable historical inspection
    HISTORICAL_INSPECTION_ENABLED = True

    # Enable performance monitoring
    PERFORMANCE_MONITORING_ENABLED = True

    # Enable query caching
    QUERY_CACHING_ENABLED = True

    @classmethod
    def is_feature_enabled(cls, feature_name: str) -> bool:
        """Check if a feature is enabled.

        Args:
            feature_name: Name of the feature

        Returns:
            True if feature is enabled, False otherwise
        """
        feature_attr = f"{feature_name.upper()}_ENABLED"
        return getattr(cls, feature_attr, False)


class OptimizationStrategy:
    """Optimization strategy for different scenarios."""

    @staticmethod
    def get_query_optimization_hints(query_type: str) -> dict:
        """Get optimization hints for a query type.

        Args:
            query_type: Type of query (task_list, step_tree, etc.)

        Returns:
            Dictionary of optimization hints
        """
        hints = {
            "task_list": {
                "use_index": "idx_tasks_session_id",
                "limit": 100,
                "cache_ttl": 300,
            },
            "step_tree": {
                "use_index": "idx_execution_steps_task_id",
                "eager_load": ["children"],
                "cache_ttl": 600,
            },
            "step_search": {
                "use_index": "idx_execution_steps_name",
                "limit": 50,
                "cache_ttl": 60,
            },
        }
        return hints.get(query_type, {})

    @staticmethod
    def get_frontend_optimization_hints() -> dict:
        """Get optimization hints for frontend rendering.

        Returns:
            Dictionary of frontend optimization hints
        """
        return {
            "tree_rendering": {
                "virtualization": TreeRenderingConfig.VIRTUALIZATION_ENABLED,
                "threshold": TreeRenderingConfig.VIRTUALIZATION_THRESHOLD,
                "lazy_load": TreeRenderingConfig.LAZY_LOAD_CHILDREN,
                "initial_depth": TreeRenderingConfig.INITIAL_DEPTH,
            },
            "caching": {
                "enabled": QueryCacheConfig.ENABLED,
                "ttl": QueryCacheConfig.TTL_SECONDS,
            },
            "monitoring": {
                "enabled": PerformanceMonitoringConfig.ENABLED,
                "slow_threshold_ms": PerformanceMonitoringConfig.SLOW_ENDPOINT_THRESHOLD_MS,
            },
        }


def log_performance_config():
    """Log current performance configuration."""
    logger.info("=" * 60)
    logger.info("Performance Configuration")
    logger.info("=" * 60)

    logger.info("Database Pool:")
    logger.info(f"  Pool Size: {DatabasePoolConfig.POOL_SIZE}")
    logger.info(f"  Max Overflow: {DatabasePoolConfig.MAX_OVERFLOW}")
    logger.info(f"  Pool Recycle: {DatabasePoolConfig.POOL_RECYCLE}s")

    logger.info("Query Caching:")
    logger.info(f"  Enabled: {QueryCacheConfig.ENABLED}")
    logger.info(f"  TTL: {QueryCacheConfig.TTL_SECONDS}s")
    logger.info(f"  Max Entries: {QueryCacheConfig.MAX_ENTRIES}")

    logger.info("Performance Monitoring:")
    logger.info(f"  Enabled: {PerformanceMonitoringConfig.ENABLED}")
    logger.info(f"  Slow Query Threshold: {PerformanceMonitoringConfig.SLOW_QUERY_THRESHOLD_MS}ms")
    logger.info(f"  Slow Endpoint Threshold: {PerformanceMonitoringConfig.SLOW_ENDPOINT_THRESHOLD_MS}ms")

    logger.info("Tree Rendering:")
    logger.info(f"  Virtualization: {TreeRenderingConfig.VIRTUALIZATION_ENABLED}")
    logger.info(f"  Lazy Load: {TreeRenderingConfig.LAZY_LOAD_CHILDREN}")

    logger.info("Feature Flags:")
    logger.info(f"  Task Tracking: {FeatureFlagConfig.TASK_TRACKING_ENABLED}")
    logger.info(f"  Real-time Updates: {FeatureFlagConfig.REAL_TIME_UPDATES_ENABLED}")
    logger.info(f"  Historical Inspection: {FeatureFlagConfig.HISTORICAL_INSPECTION_ENABLED}")

    logger.info("=" * 60)
