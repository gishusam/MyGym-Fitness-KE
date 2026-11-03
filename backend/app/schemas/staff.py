import uuid

from backend.app.schemas.base import ApiModel


class CurrentStaff(ApiModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    status: str
