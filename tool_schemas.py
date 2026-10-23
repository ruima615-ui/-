# 保存给大模型看的工具说明书。
# 这里只描述工具，不执行工具函数。

tools = [
    {
        "type": "function",
        "function": {
            "name": "searchlearningmaterial",
            "description": (
                "根据知识点和用户的具体问题，"
                "从当前会话对应的学习资料中检索最相关的文本块。"
                "适合用于依据资料解释错题或讲解知识点。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
    "topic": {
        "type": "string",
        "description": (
            "需要检索的知识点名称，"
            "通常来自错题分析工具返回的薄弱知识点"
        ),
    },
    "query": {
        "type": "string",
        "description": (
            "需要通过当前课程资料解决的具体问题，"
            "例如：为什么访问不存在的列表索引会发生越界"
        ),
    },
},
"required": [
    "topic",
    "query",
],
"additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_current_course_wrong_questions",
            "description": (
                "分析当前学生在当前课程中的已记录错题，"
                "统计各知识点的错题数量，"
                "返回优先复习知识点和对应错题依据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_course_wrong_questions",
            "description": (
                "查询当前学生在当前课程中的错题明细，"
                "返回每道错题的题目编号、知识点和错误信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
    },
]