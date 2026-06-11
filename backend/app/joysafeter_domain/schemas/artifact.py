from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ArtifactResponse(BaseModel):
    id: uuid.UUID
    execution_id: uuid.UUID
    kind: str
    uri: str
    metadata: Optional[dict] = None
    created_at: datetime
    model_config = {"from_attributes": True}
