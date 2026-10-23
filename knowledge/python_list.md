# Python列表索引

## 1. 什么是Python列表

列表可以按照顺序保存多个数据。

```python
numbers = [10, 20, 30]
```

这个列表中一共有3个元素：

```text
10、20、30
```

## 2. 列表索引从0开始

Python使用索引访问列表中的元素。

索引与元素的对应关系是：

| 索引 | 元素 |
|---|---|
| 0 | 10 |
| 1 | 20 |
| 2 | 30 |

例如：

```python
numbers = [10, 20, 30]

print(numbers[0])
print(numbers[1])
print(numbers[2])
```

运行结果是：

```text
10
20
30
```

因此：

```python
numbers[0]
```

表示第一个元素，而不是第二个元素。

## 3. 列表的合法索引范围

列表长度可以通过`len()`获得：

```python
numbers = [10, 20, 30]

print(len(numbers))
```

运行结果是：

```text
3
```

长度为3的列表，合法的正向索引范围是：

```text
0到2
```

不应该访问索引3，因为列表中不存在第四个元素。

合法索引的计算方式是：

```text
0到len(numbers) - 1
```

## 4. 什么是索引越界

下面的代码会出错：

```python
numbers = [10, 20, 30]

print(numbers[3])
```

因为列表中只有索引0、1、2，没有索引3。

Python会抛出：

```text
IndexError
```

这类错误称为索引越界。

## 5. 如何安全遍历列表

可以直接遍历列表中的元素：

```python
numbers = [10, 20, 30]

for number in numbers:
    print(number)
```

也可以按照索引遍历：

```python
numbers = [10, 20, 30]

for i in range(len(numbers)):
    print(numbers[i])
```

`len(numbers)`等于3，因此：

```python
range(len(numbers))
```

产生的索引是：

```text
0、1、2
```

不会产生3，所以不会发生索引越界。

## 6. 学习重点

使用Python列表时需要记住：

1. 列表中的元素按照顺序保存。
2. 第一个元素的索引是0。
3. 长度为n的列表，最后一个正向索引是n - 1。
4. 访问不存在的索引会出现IndexError。
5. 可以使用`for element in list`安全地遍历列表。