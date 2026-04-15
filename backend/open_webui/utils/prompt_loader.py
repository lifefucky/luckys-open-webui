"""Prompt versioning utilities.

Loads prompt templates from YAML config files and resolves the current version.
"""

from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from open_webui.env import BACKEND_DIR

PROMPTS_DIR = BACKEND_DIR / 'open_webui' / 'prompts'


def _load_prompt_config(filename: str) -> Optional[Dict[str, Any]]:
    """Load a prompt YAML config file by name (without extension)."""
    config_path = PROMPTS_DIR / f'{filename}.yaml'
    if not config_path.exists():
        return None
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_prompt(filename: str, prompt_name: str, variables: Dict[str, str]) -> tuple[str, str]:
    """Get system and user prompt strings for a given prompt config.

    Args:
        filename: YAML filename without extension (e.g. 'presentation').
        prompt_name: Key under 'prompts' (e.g. 'generate_presentation').
        variables: Dict of variable names to values for template substitution.

    Returns:
        Tuple of (system_prompt, user_prompt).

    Raises:
        FileNotFoundError: If the YAML file or prompt key does not exist.
        KeyError: If required input_variables are missing from *variables*.
    """
    config = _load_prompt_config(filename)
    if not config:
        raise FileNotFoundError(f'Prompt config not found: {filename}.yaml')

    prompt_section = config.get('prompts', {}).get(prompt_name)
    if not prompt_section:
        raise KeyError(f'Prompt "{prompt_name}" not found in {filename}.yaml')

    current_version = prompt_section.get('current_version')
    if not current_version:
        raise KeyError(f'No current_version set for prompt "{prompt_name}" in {filename}.yaml')

    version_data = prompt_section.get('versions', {}).get(current_version)
    if not version_data:
        raise KeyError(
            f'Version "{current_version}" not found for prompt "{prompt_name}" in {filename}.yaml'
        )

    # Validate required input_variables
    required_vars = version_data.get('input_variables', [])
    missing = [v for v in required_vars if v not in variables]
    if missing:
        raise KeyError(
            f'Missing input variables for prompt "{prompt_name}" v{current_version}: {missing}'
        )

    system_template = version_data.get('system', '')
    user_template = version_data.get('user', '')

    system_prompt = system_template.format(**variables) if system_template else ''
    user_prompt = user_template.format(**variables) if user_template else ''

    return system_prompt, user_prompt
