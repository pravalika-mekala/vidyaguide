from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=2000)

    @classmethod
    def from_payload(cls, payload):
        if hasattr(cls, "model_validate"):
            return cls.model_validate(payload)
        return cls.parse_obj(payload)
