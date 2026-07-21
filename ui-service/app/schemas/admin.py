from pydantic import BaseModel


class AdminUserUpdate(BaseModel):
    password: str | None = None
    role: str | None = None


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "user"


class FeedbackRequest(BaseModel):
    session_id: str
    answer_id: str
    helpful: bool


class FeedbackSelectionRequest(BaseModel):
    selected_for_evaluation: bool
