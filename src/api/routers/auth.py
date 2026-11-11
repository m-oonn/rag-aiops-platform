from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Any, List, Literal
from pydantic import BaseModel, Field, field_validator, EmailStr

from src.database.sql_session import get_db
from src.database.models import User
from src.api.dependencies import get_current_user, require_admin
from src.settings import settings
from src.utils.security import verify_password, get_password_hash, create_access_token
from src.utils.rate_limit import limiter  # 安全最佳实践: 登录速率限制

router = APIRouter()

# 角色取值。user=普通用户，auditor=审计（可读证据原文），admin=管理员（可改他人角色）。
RoleName = Literal["user", "auditor", "admin"]

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """安全最佳实践: 密码至少包含字母和数字，防止纯数字/纯字母等弱密码。"""
        if not any(c.isalpha() for c in v):
            raise ValueError("密码必须包含至少一个字母")
        if not any(c.isdigit() for c in v):
            raise ValueError("密码必须包含至少一个数字")
        return v

class Token(BaseModel):
    access_token: str
    token_type: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    role: str = "user"


class RoleUpdate(BaseModel):
    role: RoleName

@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        or_(User.username == user_in.username, User.email == user_in.email)
    ).first()
    if user:
        # 安全最佳实践: 统一错误消息，不区分用户名/邮箱已存在，防止用户枚举
        raise HTTPException(
            status_code=409,
            detail="用户名或邮箱已被注册",
        )
    user = User(
        username=user_in.username,
        email=user_in.email,
        password_hash=get_password_hash(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/login/access-token", response_model=Token)
@limiter.limit("5/minute")  # 安全最佳实践: 限制登录尝试频率，防止暴力破解
def login_access_token(
    request: Request,
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    
    # 首个管理员的引导口：把用户名写进 ADMIN_USERNAMES，登录即提为 admin。
    # 配置驱动、幂等，不依赖"默认管理员账号"，避免默认口令留在部署里。
    if user.username in settings.ADMIN_USERNAME_SET and user.role != "admin":
        user.role = "admin"
        db.commit()

    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
    }


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)):
    """当前登录用户。前端据此决定是否显示"用户管理"入口。

    角色此前只存在于数据库里、没有任何接口能读出来，所以审计视角在 UI 上走不通。
    """
    return current_user


@router.get("/users", response_model=List[UserOut])
def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return db.query(User).order_by(User.id).all()


@router.patch("/users/{user_id}/role", response_model=UserOut)
def update_user_role(
    user_id: int,
    payload: RoleUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员修改他人角色。不允许改自己，避免把最后一个 admin 降级后锁死系统。"""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.role = payload.role
    db.commit()
    db.refresh(user)
    return user
