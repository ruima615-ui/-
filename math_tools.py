def calculator(a, b):
    """计算两个数字的加法"""

    if type(a) not in (int, float):
        raise TypeError("参数a必须是数字")

    if type(b) not in (int, float):
        raise TypeError("参数b必须是数字")

    return a + b


def multipy(a, b):
    """计算两个数字的乘法"""

    if type(a) not in (int, float):
        raise TypeError("参数a必须是数字")

    if type(b) not in (int, float):
        raise TypeError("参数b必须是数字")

    return a * b

