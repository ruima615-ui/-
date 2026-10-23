
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy import Integer
from app.core.database import Base
from sqlalchemy import Boolean, CheckConstraint, Float, JSON, UniqueConstraint

class User(Base):
    """用户表：保存学生、教师和管理员。"""

    __tablename__ = "users"

    # 用户编号，例如S001、T001、A001
    id = Column(
        String(50),
        primary_key=True
    )

    # 用户姓名
    name = Column(
        String(100),
        nullable=False
    )

    # 用户角色：student、teacher、admin
    role = Column(
        String(20),
        nullable=False,
        index=True
    )

    # 用户状态：active、disabled
    status = Column(
        String(20),
        nullable=False,
        default="active"
    )

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    # 限制 role 只能是系统支持的三个合法值。
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'teacher', 'admin')",
            name="ck_users_role"
        ),
    )


class Course(Base):
    """课程表"""

    __tablename__ = "courses"

    # 课程编号，例如COURSE001
    id = Column(
        String(50),
        primary_key=True
    )

    # 课程代码，例如PYTHON101
    code = Column(
        String(50),
        nullable=False,
        unique=True
    )

    # 课程名称
    name = Column(
        String(100),
        nullable=False
    )

    # 课程说明
    description = Column(
        Text,
        nullable=True
    )

    # 课程状态：active、archived
    status = Column(
        String(20),
        nullable=False,
        default="active"
    )

    # 创建时间
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

class Enrollment(Base):
    """学生与课程的关系,选课表"""

    __tablename__ = "enrollments"

    student_id = Column(
        String(50),
        ForeignKey("users.id"),
        primary_key=True
    )

    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        primary_key=True
    )

    enrolled_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )


class TeacherCourseAssignment(Base):
    """教师负责课程的授权关系。"""

    __tablename__ = "teacher_course_assignments"

    teacher_id = Column(
        String(50),
        ForeignKey("users.id"),
        primary_key=True,
    )
    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        primary_key=True,
    )
    assigned_by = Column(
        String(50),
        ForeignKey("users.id"),
        nullable=False,
    )
    assigned_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )


class CourseMaterial(Base):
    """教师为课程上传的一份原始学习资料。"""

    __tablename__ = "course_materials"

    id = Column(String(50), primary_key=True)
    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        nullable=False,
        index=True,
    )
    uploaded_by = Column(
        String(50),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # 来源只能由后端根据上传者身份确定。
    source_type = Column(
        String(20),
        nullable=False,
        default="teacher",
        server_default="teacher",
        index=True,
    )
    # 兼容旧资料的单标签，也可保存教师给出的逗号分隔候选知识点；
    # 实际检索标签写在每个 Chroma 片段上。
    topic = Column(
        String(100),
        nullable=False,
        default="通用",
        server_default="通用",
        index=True,
    )
    title = Column(String(200), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_extension = Column(String(20), nullable=False)
    mime_type = Column(String(100), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    checksum_sha256 = Column(String(64), nullable=False, index=True)
    source_path = Column(Text, nullable=False)
    extracted_text_path = Column(Text, nullable=True)
    extracted_text_length = Column(Integer, nullable=False, default=0)
    status = Column(
        String(30),
        nullable=False,
        default="processing",
    )
    parse_error = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'ready_for_indexing', 'parse_failed')",
            name="ck_course_materials_status",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_course_materials_size",
        ),
        CheckConstraint(
            "extracted_text_length >= 0",
            name="ck_course_materials_text_length",
        ),
        CheckConstraint(
            "source_type IN ('teacher', 'official')",
            name="ck_course_materials_source_type",
        ),
    )


class CourseMaterialChunkTopic(Base):
    """教师对资料片段知识点的复核结果，重建向量索引时仍可复用。"""

    __tablename__ = "course_material_chunk_topics"

    material_id = Column(String(50), ForeignKey("course_materials.id"), primary_key=True)
    chunk_index = Column(Integer, primary_key=True)
    content_hash = Column(String(16), nullable=False)
    topics = Column(JSON, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_material_chunk_topic_index"),
    )


class CourseMaterialIndex(Base):
    """一份课程资料在向量库中的索引状态。"""

    __tablename__ = "course_material_indexes"

    material_id = Column(
        String(50),
        ForeignKey("course_materials.id"),
        primary_key=True,
    )
    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        nullable=False,
        index=True,
    )
    collection_name = Column(String(100), nullable=False)
    embedding_model = Column(String(100), nullable=False)
    content_checksum = Column(String(64), nullable=False)
    chunk_size = Column(Integer, nullable=False)
    chunk_overlap = Column(Integer, nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)
    status = Column(
        String(20),
        nullable=False,
        default="indexing",
    )
    index_error = Column(Text, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('indexing', 'indexed', 'failed')",
            name="ck_course_material_indexes_status",
        ),
        CheckConstraint(
            "chunk_size > 0",
            name="ck_course_material_indexes_chunk_size",
        ),
        CheckConstraint(
            "chunk_overlap >= 0 AND chunk_overlap < chunk_size",
            name="ck_course_material_indexes_overlap",
        ),
        CheckConstraint(
            "chunk_count >= 0",
            name="ck_course_material_indexes_count",
        ),
    )

class CourseMaterialEmbeddingIndex(Base):
    """一份课程资料在一个 embedding 后端中的索引状态。"""

    __tablename__ = "course_material_embedding_indexes"

    material_id = Column(
        String(50),
        ForeignKey("course_materials.id"),
        primary_key=True,
    )
    backend = Column(String(20), primary_key=True)  # primary / backup

    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        nullable=False,
        index=True,
    )
    collection_name = Column(String(100), nullable=False)
    embedding_model = Column(String(100), nullable=False)
    dimension = Column(Integer, nullable=False)

    content_checksum = Column(String(64), nullable=False)
    chunk_size = Column(Integer, nullable=False)
    chunk_overlap = Column(Integer, nullable=False)
    chunk_count = Column(Integer, nullable=False, default=0)

    status = Column(String(20), nullable=False, default="indexing")
    index_error = Column(Text, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "backend IN ('primary', 'backup')",
            name="ck_material_embedding_backend",
        ),
        CheckConstraint(
            "status IN ('indexing', 'indexed', 'failed')",
            name="ck_material_embedding_status",
        ),
        CheckConstraint(
            "dimension > 0",
            name="ck_material_embedding_dimension",
        ),
        CheckConstraint(
            "chunk_size > 0 AND chunk_overlap >= 0 "
            "AND chunk_overlap < chunk_size",
            name="ck_material_embedding_chunk_size",
        ),
        CheckConstraint(
            "chunk_count >= 0",
            name="ck_material_embedding_chunk_count",
        ),
    )

class ChatSession(Base):
    """长期保存一段Agent对话"""

    __tablename__ = "chat_sessions"

    id = Column(
        String(100),
        primary_key=True
    )

    user_id = Column(
        String(50),
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        nullable=True,
        index=True
    )

    title = Column(
        String(200),
        nullable=True
    )

    status = Column(
        String(20),
        nullable=False,
        default="active"
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'closed')",
            name="ck_chat_sessions_status"
        ),
    )


class StudentSessionDiagnosis(Base):
    """Validated diagnosis handoff scoped to one student, course and chat session."""

    __tablename__ = "student_session_diagnoses"

    user_id = Column(String(50), ForeignKey("users.id"), primary_key=True)
    course_id = Column(String(50), ForeignKey("courses.id"), primary_key=True)
    session_id = Column(String(100), ForeignKey("chat_sessions.id"), primary_key=True)
    diagnoses_json = Column(Text, nullable=False)
    evidence_fingerprint = Column(String(64), nullable=False)
    validated_at = Column(DateTime, nullable=False)

class ChatMessage(Base):
    """长期保存会话中的每条消息"""

    __tablename__ = "chat_messages"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    session_id = Column(
        String(100),
        ForeignKey("chat_sessions.id"),
        nullable=False,
        index=True
    )

    role = Column(
        String(20),
        nullable=False
    )

    content = Column(
        Text,
        nullable=False
    )

    metadata_json = Column(
        Text,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_chat_messages_role"
        ),
    )


class ReviewTaskProgress(Base):
    """Student self-check and completion for a specific saved plan task."""

    __tablename__ = "review_task_progress"

    session_id = Column(String(100), ForeignKey("chat_sessions.id"), primary_key=True)
    message_id = Column(Integer, ForeignKey("chat_messages.id"), primary_key=True)
    task_id = Column(String(100), primary_key=True)
    student_id = Column(String(50), ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(String(50), ForeignKey("courses.id"), nullable=False)
    self_check_answers = Column(JSON, nullable=False)
    completed_at = Column(DateTime, nullable=False, server_default=func.now())

class UserCredential(Base):
    """用户登录凭据表"""

    __tablename__ = "user_credentials"

    user_id = Column(
        String(50),
        ForeignKey("users.id"),
        primary_key=True
    )

    password_hash = Column(
        Text,
        nullable=False
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )
class WrongQuestion(Base):
    #学生在某门课程中的一条错题记录
    __tablename__ = "wrong_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(String(50), ForeignKey("users.id"), nullable=False)
    course_id = Column(String(50), ForeignKey("courses.id"), nullable=False)
    question_id = Column(String(50), nullable=False)
    topic = Column(String(100), nullable=False)
    mistake = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    
class Question(Base):
    """课程题目，支持单选、多选、判断和简答"""

    __tablename__ = "questions"

    id = Column(String(50), primary_key=True)
    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        nullable=False,
        index=True
    )
    question_type = Column(String(30), nullable=False)
    topic = Column(String(100), nullable=False)
    # 题目难度：easy、medium、hard
    difficulty = Column(
        String(20),
        nullable=False,
        default="medium",
        server_default="medium",
    )
    # NULL 表示旧题尚未由教师按四维规则标注。
    knowledge_count_level = Column(Integer, nullable=True)
    reasoning_level = Column(Integer, nullable=True)
    transfer_level = Column(Integer, nullable=True)
    distractor_level = Column(Integer, nullable=True)
    difficulty_score = Column(Integer, nullable=True)
    stem = Column(Text, nullable=False)

    # 选择题有选项；判断题和简答题可以没有
    options = Column(JSON, nullable=True)

    # 客观题存标准答案；简答题可存参考答案
    answer_key = Column(JSON, nullable=True)
    explanation = Column(Text, nullable=True)
    max_score = Column(Float, nullable=False, default=1.0)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )


class AnswerAttempt(Base):
    """学生的一次作答"""

    __tablename__ = "answer_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(
        String(50),
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )
    question_id = Column(
        String(50),
        ForeignKey("questions.id"),
        nullable=False,
        index=True
    )

    # 单选、判断、多选、简答都用JSON表达答案
    answer = Column(JSON, nullable=False)

    # 简答题未评分时，先保持pending和空结果
    grading_status = Column(String(20), nullable=False, default="pending")
    is_correct = Column(Boolean, nullable=True)
    score = Column(Float, nullable=True)

    submitted_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now()
    )
class Exam(Base):
    """一张属于某门课程的试卷"""

    __tablename__ = "exams"

    id = Column(String(50), primary_key=True)
    course_id = Column(
        String(50),
        ForeignKey("courses.id"),
        nullable=False,
        index=True,
    )
    # 历史试卷可能没有创建人；新试卷由教师创建时必须写入。
    created_by = Column(
        String(50),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    title = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    duration_minutes = Column(Integer, nullable=False)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'closed')",
            name="ck_exams_status",
        ),
        CheckConstraint(
            "duration_minutes > 0",
            name="ck_exams_duration",
        ),
    )


class ExamQuestion(Base):
    """试卷包含的题目、顺序和该题在试卷中的分值"""

    __tablename__ = "exam_questions"

    exam_id = Column(
        String(50),
        ForeignKey("exams.id"),
        primary_key=True,
    )
    question_id = Column(
        String(50),
        ForeignKey("questions.id"),
        primary_key=True,
    )
    position = Column(Integer, nullable=False)
    points = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "position",
            name="uq_exam_question_position",
        ),
        CheckConstraint(
            "position > 0",
            name="ck_exam_question_position",
        ),
        CheckConstraint(
            "points > 0",
            name="ck_exam_question_points",
        ),
    )


class ExamAttempt(Base):
    """一名学生参加一场考试的记录"""

    __tablename__ = "exam_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_id = Column(
        String(50),
        ForeignKey("exams.id"),
        nullable=False,
        index=True,
    )
    student_id = Column(
        String(50),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    status = Column(
        String(20),
        nullable=False,
        default="in_progress",
    )
    total_score = Column(Float, nullable=True)
    started_at = Column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    submitted_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "student_id",
            name="uq_exam_attempt_student",
        ),
        CheckConstraint(
            "status IN ('in_progress', 'pending_review', 'graded')",
            name="ck_exam_attempt_status",
        ),
    )


class ExamAnswer(Base):
    """一次考试中，学生对一道试卷题目的答案和得分"""

    __tablename__ = "exam_answers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_attempt_id = Column(
        Integer,
        ForeignKey("exam_attempts.id"),
        nullable=False,
        index=True,
    )
    question_id = Column(
        String(50),
        ForeignKey("questions.id"),
        nullable=False,
    )
    answer = Column(JSON, nullable=False)
    grading_status = Column(
        String(20),
        nullable=False,
        default="pending",
    )
    is_correct = Column(Boolean, nullable=True)
    score = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "exam_attempt_id",
            "question_id",
            name="uq_exam_answer_question",
        ),
        CheckConstraint(
            "grading_status IN ('pending', 'graded')",
            name="ck_exam_answer_grading_status",
        ),
    )
