"""Savi Teammate connectors — Phase T5 (pluggable interfaces)."""

from app.services.connectors.base import CONNECTOR_TYPES, ConnectorResult
from app.services.connectors.registry import get_connector

__all__ = ["CONNECTOR_TYPES", "ConnectorResult", "get_connector"]
