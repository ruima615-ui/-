import requests


BASE_URL = "http://127.0.0.1:8000"


def call_api(method, path, token, data=None):
    """调用 FastAPI，返回 (结果, 错误信息)。"""
    try:
        response = requests.request(
            method=method,
            url=f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=data,
            timeout=30,
        )
    except requests.RequestException as error:
        return None, f"无法连接后端：{error}"

    try:
        result = response.json()
    except ValueError:
        return None, f"后端返回了非 JSON 内容：HTTP {response.status_code}"

    if not response.ok:
        return None, f"HTTP {response.status_code}：{result.get('detail', result)}"

    return result, None