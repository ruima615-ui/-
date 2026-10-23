# Python函数中的print和return

## 1. print的作用

`print()`负责把内容显示在终端中。

例如：

```python
def add(a, b):
    print(a + b)

add(2, 3)
```

终端会显示：

```text
5
```

但是，显示结果不等于函数返回了结果。

## 2. return的作用

`return`负责把函数内部的结果交给函数调用的位置。

例如：

```python
def add(a, b):
    return a + b

result = add(2, 3)

print(result)
```

变量`result`会得到：

```text
5
```

## 3. 为什么结果会是None

如果函数没有执行`return`，Python会默认返回`None`。

例如：

```python
def add(a, b):
    print(a + b)

result = add(2, 3)

print(result)
```

运行结果是：

```text
5
None
```

第一个`5`来自函数内部的`print()`。

第二个`None`是变量`result`的值，因为函数没有使用`return`返回计算结果。

## 4. print和return的区别

| 对比项 | print | return |
|---|---|---|
| 主要作用 | 显示内容 | 返回结果 |
| 结果能否赋值给变量 | 不能 | 能 |
| 是否结束当前函数 | 不一定 | 是 |
| 没有return时 | 可以正常显示 | 默认返回None |

## 5. 学习重点

1. `print()`只是显示内容。
2. `return`才会把结果返回给调用位置。
3. 函数没有`return`时，默认返回`None`。
4. 需要继续使用计算结果时，应该使用`return`。