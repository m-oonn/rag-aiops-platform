from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Any
from pydantic import BaseModel, Field, field_validator, EmailStr

from src.database.sql_session import get_db
from src.database.models import User
from src.utils.security import verify_password, get_password_hash, create_access_token
from src.utils.rate_limit import limiter  # 安全最佳实践: 登录速率限制

router = APIRouter()

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
    
    return {
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
    }
