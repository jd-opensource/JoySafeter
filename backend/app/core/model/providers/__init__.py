"""
Model provider module.
"""

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import List, Optional, Type

from .base import BaseProvider, ModelType
from .Custom import CustomProvider

# backward compatibility: explicit import of existing provider
from .OpenaiApiCompatible import OpenAIAPICompatibleProvider

logger = logging.getLogger(__name__)

# provider class cache
_provider_classes_cache: Optional[List[Type[BaseProvider]]] = None


def _discover_provider_classes() -> List[Type[BaseProvider]]:
    """
    Auto-discover all classes that inherit from BaseProvider.

    Returns:
        List of all discovered provider classes.
    """
    global _provider_classes_cache

    if _provider_classes_cache is not None:
        return _provider_classes_cache

    provider_classes: List[Type[BaseProvider]] = []

    # get current package path
    package_path = Path(__file__).parent
    package_name = __name__

    # iterate over all modules in the directory
    for importer, modname, ispkg in pkgutil.iter_modules([str(package_path)]):
        # skip __init__ and base modules
        if modname in ("__init__", "base"):
            continue

        try:
            # dynamically import the module
            module = importlib.import_module(f".{modname}", package=package_name)

            # iterate over all members in the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # check if it is a subclass of BaseProvider (excluding BaseProvider itself)
                if issubclass(obj, BaseProvider) and obj is not BaseProvider and obj.__module__ == module.__name__:
                    provider_classes.append(obj)
        except Exception as e:
            # log warning on import failure without interrupting the program
            import warnings

            warnings.warn(f"Failed to import provider module '{modname}': {e}", ImportWarning)

    _provider_classes_cache = provider_classes
    return provider_classes


def get_all_provider_classes() -> List[Type[BaseProvider]]:
    """
    Return all provider classes.

    Returns:
        List of all provider classes.
    """
    return _discover_provider_classes()


def get_all_provider_instances() -> List[BaseProvider]:
    """
    Return all provider instances.

    Returns:
        List of all provider instances.
    """
    classes = get_all_provider_classes()
    instances = []
    for cls in classes:
        try:
            # Try to instantiate - most providers have __init__ that calls super().__init__()
            instance = cls()  # type: ignore[call-arg]
            instances.append(instance)
        except TypeError:
            logger.warning("Failed to instantiate provider %s, skipping", cls.__name__, exc_info=True)
            continue
    return instances


__all__ = [
    "BaseProvider",
    "ModelType",
    "OpenAIAPICompatibleProvider",
    "CustomProvider",
    "get_all_provider_classes",
    "get_all_provider_instances",
]
