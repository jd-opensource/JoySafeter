import json
import re
from typing import List

from langchain_core.tools import tool
from loguru import logger


@tool
def valid_json_array(json_array_str: str) -> str:
    """
    Verify that the string is a JSON array.

    :param json_array_str:
    :return: ok if string is a JSON array else error message
    """
    try:
        temp = json.loads(json_array_str)
        if isinstance(temp, list):
            return "ok"
        else:
            return f"Error: expect json array str but got {type(temp)} str instead"
    except Exception as e:
        logger.error(f"Error parsing JSON array: {e}, json_array_str: {json_array_str}")
        raise e


@tool
def valid_json_dict(json_dict_str: str) -> str:
    """
    Verify that the string is a JSON dict.

    :param json_dict_str:
    :return: ok if string is a JSON array else error message
    """
    try:
        temp = json.loads(json_dict_str)
        if not isinstance(temp, dict):
            return "ok"
        else:
            return f"Error: expect json dict str but got {type(temp)} instead"
    except Exception as e:
        logger.error(f"Error parsing JSON array: {e}, json_array_str: {json_dict_str}")
        raise e


@tool
def valid_json_dict_plus(json_dict_str: str, keys: List[str]) -> str:
    """
    Verify that the string is a JSON dict and with specified keys.

    :param json_dict_str:
    :param keys: Fields must exist in JSON dict, any one will be a path expression for accessing nested dictionary elements.
        such as : a.b.c, a[0].b.c
    :return: ok if string is a JSON dict and keys exist else error message
    """
    try:
        # Parse the JSON string
        data = json.loads(json_dict_str)

        # Check if it's a dictionary
        if not isinstance(data, dict):
            return f"Error: expect json dict str but got {type(data)} instead"

        # Validate each key path
        for key_path in keys:
            if not _validate_key_path(data, key_path):
                return f'Error: key path "{key_path}" does not exist in the JSON dict'

        return "ok"
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSON dict: {e}, json_dict_str: {json_dict_str}")
        return f"Error: invalid JSON format - {str(e)}"
    except Exception as e:
        logger.error(f"Error validating JSON dict: {e}, json_dict_str: {json_dict_str}")
        raise e


def _validate_key_path(data: dict, key_path: str) -> bool:
    """
    Validate if a key path exists in the nested dictionary.

    Supports path expressions like:
    - 'a.b.c' for nested dict access
    - 'a[0].b' for array index access
    - 'a[0][1].b' for multiple array indices

    :param data: The dictionary to validate against
    :param key_path: The path expression to validate
    :return: True if the path exists, False otherwise
    """
    # Split the path by dots, but preserve array indices
    # Convert 'a[0].b[1].c' to ['a', '[0]', 'b', '[1]', 'c']
    parts = re.split(r"\.(?![^\[]*\])", key_path)

    current = data

    for part in parts:
        # Check if this part contains array indices
        # Match pattern like 'key[0][1]' or just 'key' or just '[0]'
        matches = re.findall(r"^([^\[]*)((?:\[\d+\])*)$", part)
        if not matches:
            return False

        key_name, indices = matches[0]

        # Access the key if it exists
        if key_name:
            if not isinstance(current, dict) or key_name not in current:
                return False
            current = current[key_name]

        # Process array indices if any
        if indices:
            # Extract all indices like [0][1] -> ['0', '1']
            index_list = re.findall(r"\[(\d+)\]", indices)
            for idx_str in index_list:
                idx = int(idx_str)
                if not isinstance(current, list) or idx >= len(current):
                    return False
                current = current[idx]

    return True
