"""
DSL v2 parser for Practice configurations.

Parses YAML into PracticeConfig models.
"""

import yaml
from typing import Any

from praxis_core.dsl.practice_config import PracticeConfig, PracticeAction
from praxis_core.dsl.triggers import Trigger, Schedule, Cadence, Event, EventType
from praxis_core.dsl.conditions import Condition
from praxis_core.dsl.actions import CreateAction, CollateAction, CollateTarget
from praxis_core.dsl.templates import TaskTemplate, PriorityTemplate


class DSLParseError(Exception):
    """Error parsing DSL v2 content."""
    pass


def parse_practice(yaml_content: str) -> PracticeConfig:
    """
    Parse a Practice configuration from YAML.

    Args:
        yaml_content: YAML string with practice configuration

    Returns:
        PracticeConfig model

    Raises:
        DSLParseError: If YAML is invalid or missing required fields
    """
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise DSLParseError(f"Invalid YAML: {e}")

    if not isinstance(data, dict):
        raise DSLParseError(f"Expected mapping, got {type(data).__name__}")

    if "practice" not in data:
        raise DSLParseError("Missing 'practice' key")

    return PracticeConfig.from_dict(data)


def parse_practices(yaml_content: str) -> list[PracticeConfig]:
    """
    Parse multiple Practice configurations from multi-document YAML.

    Args:
        yaml_content: YAML string with one or more practice configurations

    Returns:
        List of PracticeConfig models
    """
    try:
        documents = list(yaml.safe_load_all(yaml_content))
    except yaml.YAMLError as e:
        raise DSLParseError(f"Invalid YAML: {e}")

    practices = []
    for doc in documents:
        if doc is None:
            continue
        if "practice" in doc:
            practices.append(PracticeConfig.from_dict(doc))

    return practices


def serialize_practice(config: PracticeConfig) -> str:
    """
    Serialize a PracticeConfig to YAML.

    Args:
        config: PracticeConfig model

    Returns:
        YAML string
    """
    data = config.to_dict()
    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
