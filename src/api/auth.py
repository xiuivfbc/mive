from fastapi import APIRouter, Depends

from src.api.deps import get_current_user
from src.db.models import M9User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def get_me(current_user: M9User = Depends(get_current_user)):
    """开源单人自托管：无需登录，返回固定管理员账号的展示信息。"""
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "avatar_url": current_user.avatar_url,
        "is_admin": current_user.is_admin,
        "preferred_language": current_user.preferred_language,
    }
