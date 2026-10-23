import argparse

from app.core.database import SessionLocal
from app.services.material_index_service import (
    index_ready_course_materials_dual,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将已解析课程资料写入 Chroma 向量索引",
    )
    parser.add_argument(
        "--course-id",
        default=None,
        help="只索引指定课程；不填写时索引全部待处理资料",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        results = index_ready_course_materials_dual(
            db=db,
            course_id=args.course_id,
        )
        print(f"完成资料数量：{len(results)}")
        for result in results:
            print(result)
    finally:
        db.close()


if __name__ == "__main__":
    main()
