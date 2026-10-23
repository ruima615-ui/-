from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status

from app.api.exam_dependencies import get_db
from app.schemas.auth import RegisterRequest
from app.schemas.auth import RegisterResponse
from app.services.auth_service import register_student
from app.services.teacher_service import register_teacher_account
from app.schemas.auth import TeacherRegisterRequest
from app.schemas.auth import TeacherAccountResponse

#注册接口
router = APIRouter(
    prefix="/auth",
    tags=["认证"]
)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED
)
def register(
    request: RegisterRequest,
    db=Depends(get_db),
):
    try:
        user = register_student(
            db=db,
            user_id=request.user_id,
            name=request.name,
            plain_password=request.password
        )

        return RegisterResponse(
            user_id=user.id,
            name=user.name,
            role=user.role,
            status=user.status
        )

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error)
        ) from error

@router.post(
    "/register/teacher",
    response_model=TeacherAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_teacher(
    request: TeacherRegisterRequest,
    db=Depends(get_db),
):
    """教师自助注册，注册后等待管理员审核。"""

    try:
        teacher = register_teacher_account(
            db=db,
            user_id=request.user_id,
            name=request.name,
            plain_password=request.password,
        )
        return TeacherAccountResponse(
            user_id=teacher.id,
            name=teacher.name,
            role=teacher.role,
            status=teacher.status,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
#注册接口负责接收注册请求，调用register_student(),把结果转换成RegisterReponse


#登录接口
from typing import Annotated

from fastapi.security import OAuth2PasswordRequestForm

from app.schemas.auth import TokenResponse
from app.services.auth_service import authenticate_user

#规定登录接口成功时，应该向客户端返回什么格式的数据
@router.post("/login", response_model=TokenResponse)
def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db=Depends(get_db),
):
    try:
        result = authenticate_user(
            db=db,
            user_id=form_data.username,
            plain_password=form_data.password
        )

        if result is None:
            raise HTTPException(
                status_code=401,
                detail="用户编号或密码错误",
                headers={"WWW-Authenticate": "Bearer"}
            )

        user = result["user"]
        return TokenResponse(
            access_token=result["access_token"],
            token_type="bearer",
            user_id=user.id,
            role=user.role
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
