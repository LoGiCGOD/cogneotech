from pydantic import BaseModel

class ConnectionInput(BaseModel):
    host: str
    port: int
    username: str
    password: str

class ConnectionOutput(BaseModel):
    id: str
    host: str
    port: int
    username: str