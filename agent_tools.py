# agent_tools.py
# 统一导出学习助手使用的工具函数


# 从math_tools.py导入计算工具
from math_tools import (
    calculator,
    multipy
)


# 从student_tools.py导入学生数据工具
from student_tools import (
    getstudentscore,
    getwrongquestions,
    analyzewrongquestions
)


# 从rag_tools.py导入学习资料检索工具
from rag_tools import (
    searchlearningmaterial
)