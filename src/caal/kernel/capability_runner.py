from __future__ import annotations

from typing import Dict

from caal.kernel.contracts import Capability


class CapabilityRunner:
    def __init__(self, capabilities: Dict[str, Capability]) -> None:
        self._capabilities = capabilities

    def run(self, name: str, state: Dict[str, object], context: Dict[str, object]) -> Dict[str, object]:
        capability = self._capabilities.get(name)
        if capability is None:
            raise ValueError(f"Capability '{name}' is not registered")
        return capability.execute(state=state, context=context)
