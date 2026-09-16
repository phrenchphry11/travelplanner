from fastapi import APIRouter, Depends

from app.auth import current_user
from app.models import User

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name}
