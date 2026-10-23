"""把教师上传的 UTF-8 CSV 转为题库批量导入请求。"""

import csv
import io
import json


CSV_COLUMNS = (
    "question_type", "topic", "stem", "options", "answer_key",
    "explanation", "max_score", "knowledge_count_level",
    "reasoning_level", "transfer_level", "distractor_level",
)


def parse_questions_csv(data: bytes, course_id: str) -> list[dict]:
    if len(data) > 2_000_000:
        raise ValueError("CSV 文件不能超过 2 MB")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("请上传 UTF-8 编码的 CSV 文件") from error
    reader = csv.DictReader(io.StringIO(content))
    required = {"question_type", "topic", "stem", "answer_key"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV 缺少必填列：question_type、topic、stem、answer_key")
    items = []
    for number, row in enumerate(reader, start=2):
        if not any(value and value.strip() for value in row.values() if isinstance(value, str)):
            continue
        if None in row:
            raise ValueError(f"第 {number} 行列数超过表头；含逗号的内容需用双引号包裹")
        try:
            options_text = (row.get("options") or "").strip()
            item = {
                "course_id": course_id,
                "question_type": (row.get("question_type") or "").strip(),
                "topic": (row.get("topic") or "").strip(),
                "stem": (row.get("stem") or "").strip(),
                "options": json.loads(options_text) if options_text else None,
                "answer_key": json.loads((row.get("answer_key") or "").strip()),
                "explanation": (row.get("explanation") or "").strip() or None,
                "max_score": float((row.get("max_score") or "1").strip()),
            }
            for field in CSV_COLUMNS[-4:]:
                item[field] = int((row.get(field) or "0").strip())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"第 {number} 行格式错误：{error}") from error
        items.append(item)
        if len(items) > 200:
            raise ValueError("每次最多导入 200 道题")
    if not items:
        raise ValueError("CSV 中没有题目")
    return items
