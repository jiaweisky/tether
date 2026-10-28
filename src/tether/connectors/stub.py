"""Base for connectors whose platform SDK is not yet integrated.

Such a connector declares its capabilities but inherits the base ``Unsupported``
behaviour for every primitive until it is implemented and verified against the
real platform.
"""

from __future__ import annotations

from tether.capabilities import Capabilities
from tether.connectors.base import BaseConnector


class ScaffoldConnector(BaseConnector):
    def __init__(self, name: str, capabilities: Capabilities) -> None:
        super().__init__(capabilities)
        self.name = name
