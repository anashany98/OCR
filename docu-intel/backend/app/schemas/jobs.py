from datetime import datetime

from pydantic import BaseModel


class ExtractionJobRead(BaseModel):
    id: int
    document_id: int
    job_type: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    retries: int

    model_config = {"from_attributes": True}

