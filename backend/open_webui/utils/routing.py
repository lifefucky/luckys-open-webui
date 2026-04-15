# backend/open_webui/utils/routing.py
"""Model routing utilities for selecting optimal models for specific tasks."""

from typing import List, Dict, Any, Optional


class NoFunctionCallingModelError(Exception):
    """Raised when no function-calling capable model is available."""
    pass


def get_function_calling_model(
    available_models: List[Dict[str, Any]],
    preferred_model_id: Optional[str] = None,
) -> str:
    """Select a function-calling capable model from available models.

    Args:
        available_models: List of model dicts with metadata.
        preferred_model_id: Optional preferred model ID to use if available.

    Returns:
        Model ID string for function calling tasks.

    Raises:
        NoFunctionCallingModelError: If no suitable model is found.

    Note:
        Currently returns a stub placeholder. Future implementation will
        evaluate models based on:
        - Function calling capability support
        - Cost per token
        - Benchmark scores (tool use, reasoning, etc.)
        - User access permissions
    """
    # TODO: Implement intelligent model selection based on cost, benchmarks,
    # and function calling capability detection.
    # See BACKLOG.md for full feature specification.

    if preferred_model_id:
        for model in available_models:
            if model.get('id') == preferred_model_id:
                return preferred_model_id

    # Stub: fallback to first available model
    if available_models:
        return available_models[0].get('id', '')

    raise NoFunctionCallingModelError(
        'No function-calling capable model available. '
        'Please configure a model that supports tool/function calling '
        'or set TASK_MODEL in environment variables.'
    )
