import json
import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
import httpx
from openai import OpenAI, OpenAIError
from langchain_core.embeddings import Embeddings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1024"))
PRIMARY_MODEL = os.getenv("PRIMARY_EMBEDDING_MODEL", "text-embedding-v4")
BACKUP_MODEL = os.getenv("BACKUP_EMBEDDING_MODEL", "bge-m3")


class EmbeddingUnavailable(RuntimeError):
    """某个向量模型当前无法提供有效结果。"""


def embed_texts(texts: list[str], backend: str) -> list[list[float]]:
    """
    backend='primary'：百炼 text-embedding-v4
    backend='backup'：本地 Ollama bge-m3

    此函数只负责生成向量，不负责决定搜索哪份索引。
    """
    if not texts:
        return []

    if backend == "primary":
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise EmbeddingUnavailable("没有配置 DASHSCOPE_API_KEY")

        try:
            # 本机可能配置了失效的系统代理；百炼连接默认直连，需要代理时可显式开启。
            trust_env = os.getenv("DASHSCOPE_TRUST_ENV", "false").lower() in {"1", "true", "yes"}
            with OpenAI(
                api_key=api_key,
                base_url=os.getenv("DASHSCOPE_BASE_URL"),
                timeout=10.0,
                max_retries=0,
                http_client=httpx.Client(trust_env=trust_env, timeout=10.0),
            ) as client:
                response = client.embeddings.create(
                    model=PRIMARY_MODEL,
                    input=texts,
                    dimensions=DIMENSION,
                    encoding_format="float",
                )
            vectors = [
                item.embedding
                for item in sorted(response.data, key=lambda item: item.index)
            ]
        except OpenAIError as exc:
            raise EmbeddingUnavailable(
                f"百炼向量服务不可用：{type(exc).__name__}"
            ) from exc

    elif backend == "backup":
        payload = json.dumps({
            "model": BACKUP_MODEL,
            "input": texts,
            "truncate": False,
        }).encode("utf-8")

        request = Request(
            os.getenv(
                "OLLAMA_EMBED_URL",
                "http://127.0.0.1:11434/api/embed",
            ),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=60) as response:
                result = json.load(response)
            vectors = result["embeddings"]
        except (URLError, TimeoutError, KeyError, ValueError) as exc:
            raise EmbeddingUnavailable(
                f"本地 Ollama 向量服务不可用：{type(exc).__name__}"
            ) from exc

    else:
        raise ValueError(f"未知的向量后端：{backend}")

    if len(vectors) != len(texts):
        raise EmbeddingUnavailable("返回向量数量与输入文本数量不一致")

    if any(len(vector) != DIMENSION for vector in vectors):
        raise EmbeddingUnavailable(
            f"返回向量维度不是预期的 {DIMENSION}"
        )

    return vectors


class CourseEmbeddings(Embeddings):
    """将固定后端适配为 Chroma 使用的 LangChain Embeddings 接口。"""

    def __init__(self, backend: str):
        if backend not in {"primary", "backup"}:
            raise ValueError(f"未知的向量后端：{backend}")
        self.backend = backend

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_texts(texts, self.backend)

    def embed_query(self, text: str) -> list[float]:
        return embed_texts([text], self.backend)[0]
