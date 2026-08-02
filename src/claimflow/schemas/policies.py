from pydantic import BaseModel


class PolicyFile(BaseModel):
    filename: str
    domain: str
    authority: str
    size_bytes: int


class PolicyIndexStatus(BaseModel):
    status: str
    chunk_count: int
