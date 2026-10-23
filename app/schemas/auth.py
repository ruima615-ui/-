from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """学生注册时提交的数据"""

    user_id: str = Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9_-]+$"
    )
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class RegisterResponse(BaseModel):
    """注册成功后返回的数据"""

    user_id: str
    name: str
    role: str
    status: str
class TokenResponse(BaseModel):
    """登录成功后返回的数据"""

    access_token: str
    token_type: str
    user_id: str
    role: str


class TeacherRegisterRequest(RegisterRequest):
    """教师自助注册时提交的数据。"""


class TeacherAccountResponse(RegisterResponse):
    """教师账号创建结果。"""
