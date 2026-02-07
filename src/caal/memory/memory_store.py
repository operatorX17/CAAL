from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MemoryProposal:
    user_id: str
    data: Dict[str, Any]


class MemoryStore:
    def __init__(self) -> None:
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._pending: Dict[str, MemoryProposal] = {}

    def get_user_memory(self, user_id: str) -> Dict[str, Any]:
        return self._memory.get(user_id, {})

    def propose_update(self, user_id: str, data: Dict[str, Any]) -> MemoryProposal:
        proposal = MemoryProposal(user_id=user_id, data=data)
        self._pending[user_id] = proposal
        return proposal

    def commit_update(self, user_id: str) -> Optional[MemoryProposal]:
        proposal = self._pending.pop(user_id, None)
        if proposal:
            existing = self._memory.get(user_id, {})
            existing.update(proposal.data)
            self._memory[user_id] = existing
        return proposal
