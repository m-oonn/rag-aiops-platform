from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Any
from pydantic import BaseModel

from src.database.sql_session import get_db
from src.database.models import User
from src.utils.security import verify_password, get_password_hash, create_access_token
from src.settings import settings

router = APIRouter()

class UserCreate(BaseModel):
    username: str
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class UserOut(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool

@router.post("/register", response_model=UserOut)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        or_(User.username == user_in.username, User.email == user_in.email)
    ).first()
    if user:
        if user.username == user_in.username:
            detail = "The user with this username already exists in the system."
        else:
            detail = "The user with this email already exists in the system."
            
        raise HTTPException(
            status_code=400,
            detail=detail,
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
def login_access_token(
    db: Session = Depends(get_db), form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    elif not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    
    access_token_expires = settings.ACCESS_TOKEN_EXPIRE_MINUTES
    return {
        "access_token": create_access_token(
            user.id,
        ),
        "token_type": "bearer",
    }
