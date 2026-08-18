"""
数学工具

@Author: 花海
@Date: 2026/08/14 10:00
@Description: 通用数学工具类，覆盖数值处理、统计、向量相似度与转换解析。
              浮点精度问题统一通过 Decimal（精确十进制）与 epsilon（近似比较）处理，
              避免 0.1 + 0.2 != 0.3 这类二进制浮点误差。
"""
from __future__ import annotations

import math
from collections import Counter
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from typing import Sequence

# 可参与精确转换的数值类型
Number = float | int | str | Decimal


class MathUtil:
    """通用数学工具类：数值处理、统计、向量相似度与转换解析"""

    # ------------------------------------------------------------------
    # 数值工具
    # ------------------------------------------------------------------

    @staticmethod
    def safe_divide(a: float, b: float, default: float | None = None) -> float | None:
        """安全除法，除数为 0 时返回默认值而非抛异常。

        :param a: 被除数
        :param b: 除数
        :param default: 除数为 0 时的返回值
        :return: 商或默认值
        """
        try:
            return a / b
        except ZeroDivisionError:
            return default

    @staticmethod
    def clamp(value: float, min_value: float, max_value: float) -> float:
        """将数值裁剪到 [min_value, max_value] 闭区间内。

        :param value: 待裁剪的数值
        :param min_value: 下限
        :param max_value: 上限
        :return: 裁剪后的数值
        """
        if min_value > max_value:
            raise ValueError(f"min_value({min_value}) 不能大于 max_value({max_value})")
        return max(min_value, min(value, max_value))

    @staticmethod
    def round_half_up(value: float, decimals: int = 0) -> float:
        """四舍五入（0.5 向上进位），区别于银行家舍入。

        :param value: 待舍入的数值
        :param decimals: 保留小数位数
        :return: 舍入后的数值
        """
        quant = Decimal(1).scaleb(-decimals)
        return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))

    @staticmethod
    def round_half_even(value: float, decimals: int = 0) -> float:
        """银行家舍入（0.5 向最近的偶数进位，与 Python 内建 round 语义一致但更精确）。

        :param value: 待舍入的数值
        :param decimals: 保留小数位数
        :return: 舍入后的数值
        """
        quant = Decimal(1).scaleb(-decimals)
        return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_EVEN))

    @staticmethod
    def format_percent(value: float, decimals: int = 2, with_symbol: bool = True) -> str:
        """将小数格式化为百分比字符串（如 0.1234 -> 12.34%）。

        :param value: 待格式化的小数（0.1234 表示 12.34%）
        :param decimals: 保留小数位数
        :param with_symbol: 是否追加百分号
        :return: 百分比字符串
        """
        text = f"{value * 100:.{decimals}f}"
        return f"{text}%" if with_symbol else text

    @staticmethod
    def percent(value: float, total: float, decimals: int = 2) -> float:
        """计算 value 占 total 的百分比（如 percent(3, 4) -> 75.0）。

        :param value: 部分值
        :param total: 总值
        :param decimals: 保留小数位数
        :return: 百分比数值
        """
        if total == 0:
            raise ZeroDivisionError("total 不能为 0")
        return MathUtil.round_half_up(value / total * 100, decimals)

    @staticmethod
    def float_eq(a: float, b: float, epsilon: float = 1e-9) -> bool:
        """浮点近似相等比较，带 epsilon 容差，避免 0.1 + 0.2 != 0.3 的坑。

        :param a: 数值 a
        :param b: 数值 b
        :param epsilon: 允许的绝对误差
        :return: 是否近似相等
        """
        return abs(a - b) <= epsilon

    @staticmethod
    def in_range(
        value: float,
        min_value: float,
        max_value: float,
        include_min: bool = True,
        include_max: bool = True,
    ) -> bool:
        """判断数值是否落在指定区间内，可分别控制上下边界是否包含。

        :param value: 待判断的数值
        :param min_value: 区间下限
        :param max_value: 区间上限
        :param include_min: 是否包含下限
        :param include_max: 是否包含上限
        :return: 是否在区间内
        """
        if min_value > max_value:
            raise ValueError(f"min_value({min_value}) 不能大于 max_value({max_value})")
        left_ok = min_value <= value if include_min else min_value < value
        right_ok = value <= max_value if include_max else value < max_value
        return left_ok and right_ok

    # ------------------------------------------------------------------
    # 统计工具
    # ------------------------------------------------------------------

    @staticmethod
    def mean(values: Sequence[float]) -> float:
        """计算均值。

        :param values: 数值序列
        :return: 均值
        """
        if not values:
            raise ValueError("values 不能为空")
        return sum(values) / len(values)

    @staticmethod
    def median(values: Sequence[float]) -> float:
        """计算中位数。

        :param values: 数值序列
        :return: 中位数
        """
        if not values:
            raise ValueError("values 不能为空")
        sorted_values = sorted(values)
        n = len(sorted_values)
        mid = n // 2
        if n % 2 == 1:
            return sorted_values[mid]
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2

    @staticmethod
    def mode(values: Sequence[float]) -> float:
        """计算众数（出现次数最多的值，平局时返回最先出现的那个）。

        :param values: 数值序列
        :return: 众数
        """
        if not values:
            raise ValueError("values 不能为空")
        return Counter(values).most_common(1)[0][0]

    @staticmethod
    def variance(values: Sequence[float], sample: bool = True) -> float:
        """计算方差。

        :param values: 数值序列
        :param sample: True 为样本方差（除以 n-1），False 为总体方差（除以 n）
        :return: 方差
        """
        if len(values) < 2:
            raise ValueError("至少需要 2 个数据点")
        m = MathUtil.mean(values)
        ss = sum((x - m) ** 2 for x in values)
        return ss / (len(values) - 1 if sample else len(values))

    @staticmethod
    def std(values: Sequence[float], sample: bool = True) -> float:
        """计算标准差。

        :param values: 数值序列
        :param sample: True 为样本标准差，False 为总体标准差
        :return: 标准差
        """
        return math.sqrt(MathUtil.variance(values, sample))

    @staticmethod
    def percentile(values: Sequence[float], q: float) -> float:
        """计算分位数（线性插值法，等价于 numpy.percentile 默认行为）。

        :param values: 数值序列
        :param q: 百分位（0-100），如 50 表示中位数、95 表示 P95
        :return: 分位数值
        """
        if not values:
            raise ValueError("values 不能为空")
        if not 0 <= q <= 100:
            raise ValueError("q 必须在 0-100 之间")
        sorted_values = sorted(values)
        rank = (q / 100) * (len(sorted_values) - 1)
        lower = int(math.floor(rank))
        upper = int(math.ceil(rank))
        if lower == upper:
            return sorted_values[lower]
        weight = rank - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight

    @staticmethod
    def moving_average(values: Sequence[float], window: int) -> list[float]:
        """计算滑动窗口均值。

        :param values: 数值序列
        :param window: 窗口大小
        :return: 滑动均值序列（长度 = len(values) - window + 1）
        """
        if window <= 0:
            raise ValueError(f"window({window}) 必须大于 0")
        if window > len(values):
            return []
        return [sum(values[i:i + window]) / window for i in range(len(values) - window + 1)]

    @staticmethod
    def trim_mean(values: Sequence[float], proportion: float = 0.1) -> float:
        """截尾均值：去掉两端指定比例的数据后求均值，抑制异常值影响。

        :param values: 数值序列
        :param proportion: 每端截去的比例（0-0.5）
        :return: 截尾均值
        """
        if not values:
            raise ValueError("values 不能为空")
        if not 0 <= proportion < 0.5:
            raise ValueError("proportion 必须在 [0, 0.5) 区间内")
        sorted_values = sorted(values)
        n = len(sorted_values)
        k = int(n * proportion)
        if k == 0:
            return MathUtil.mean(sorted_values)
        trimmed = sorted_values[k:n - k]
        return MathUtil.mean(trimmed) if trimmed else sorted_values[n // 2]

    @staticmethod
    def winsorize(values: Sequence[float], limits: float = 0.1) -> list[float]:
        """缩尾处理：将两端超出边界的值替换为边界值，而非删除。

        :param values: 数值序列
        :param limits: 每端缩尾的比例（0-0.5）
        :return: 缩尾后的序列（保持原顺序）
        """
        if not values:
            raise ValueError("values 不能为空")
        if not 0 <= limits < 0.5:
            raise ValueError("limits 必须在 [0, 0.5) 区间内")
        sorted_values = sorted(values)
        n = len(sorted_values)
        k = int(n * limits)
        if k == 0:
            return list(values)
        lower = sorted_values[k]
        upper = sorted_values[n - 1 - k]
        return [lower if x < lower else (upper if x > upper else x) for x in values]

    # ------------------------------------------------------------------
    # 向量工具（纯 Python 实现，等价于 numpy 对应能力，避免强制依赖）
    # ------------------------------------------------------------------

    @staticmethod
    def dot_product(a: Sequence[float], b: Sequence[float]) -> float:
        """计算两个向量的点积。

        :param a: 向量 a
        :param b: 向量 b
        :return: 点积
        """
        if len(a) != len(b):
            raise ValueError("向量长度不一致")
        return sum(x * y for x, y in zip(a, b))

    @staticmethod
    def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
        """计算两个向量的余弦相似度（[-1, 1]，零向量返回 0）。

        :param a: 向量 a
        :param b: 向量 b
        :return: 余弦相似度
        """
        dot = MathUtil.dot_product(a, b)
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def euclidean_distance(a: Sequence[float], b: Sequence[float]) -> float:
        """计算两个向量的欧氏距离。

        :param a: 向量 a
        :param b: 向量 b
        :return: 欧氏距离
        """
        if len(a) != len(b):
            raise ValueError("向量长度不一致")
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    @staticmethod
    def l2_normalize(vector: Sequence[float]) -> list[float]:
        """L2 归一化（零向量返回全 0）。

        :param vector: 待归一化向量
        :return: L2 归一化后的向量
        """
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0:
            return [0.0] * len(vector)
        return [x / norm for x in vector]

    @staticmethod
    def l1_normalize(vector: Sequence[float]) -> list[float]:
        """L1 归一化（零向量返回全 0）。

        :param vector: 待归一化向量
        :return: L1 归一化后的向量
        """
        norm = sum(abs(x) for x in vector)
        if norm == 0:
            return [0.0] * len(vector)
        return [x / norm for x in vector]

    @staticmethod
    def softmax(values: Sequence[float]) -> list[float]:
        """softmax（数值稳定：先减去最大值避免 exp 溢出）。

        :param values: 数值序列
        :return: softmax 归一化后的概率分布
        """
        if not values:
            return []
        m = max(values)
        exps = [math.exp(x - m) for x in values]
        s = sum(exps)
        return [e / s for e in exps]

    # ------------------------------------------------------------------
    # 转换与解析
    # ------------------------------------------------------------------

    @staticmethod
    def to_decimal(value: Number) -> Decimal:
        """将数值安全转换为 Decimal，避免 float 直接转 Decimal 引入的二进制误差。

        :param value: 待转换的数值（float/int/str/Decimal）
        :return: 精确的 Decimal 值
        """
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def parse_int(value: str | float | int, default: int = 0) -> int:
        """数值字符串安全解析为整数，非法输入返回默认值而非抛异常。

        :param value: 待解析的值
        :param default: 解析失败时的默认值
        :return: 整数
        """
        try:
            if isinstance(value, str):
                return int(float(value.strip()))
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def parse_float(value: str | float | int, default: float = 0.0) -> float:
        """数值字符串安全解析为浮点数，非法输入返回默认值而非抛异常。

        :param value: 待解析的值
        :param default: 解析失败时的默认值
        :return: 浮点数
        """
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def percent_to_decimal(percent_value: float) -> float:
        """百分数转小数（50 -> 0.5）。

        :param percent_value: 百分数值
        :return: 小数值
        """
        return percent_value / 100

    @staticmethod
    def decimal_to_percent(decimal_value: float) -> float:
        """小数转百分数（0.5 -> 50）。

        :param decimal_value: 小数值
        :return: 百分数值
        """
        return decimal_value * 100

    @staticmethod
    def int_to_base(n: int, base: int) -> str:
        """整数转任意进制（2-36）字符串。

        :param n: 待转换的整数
        :param base: 目标进制（2-36）
        :return: 进制字符串
        """
        if base < 2 or base > 36:
            raise ValueError("base 必须在 2-36 之间")
        if n == 0:
            return "0"
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        negative = n < 0
        n = abs(n)
        result = ""
        while n > 0:
            n, remainder = divmod(n, base)
            result = digits[remainder] + result
        return ("-" + result) if negative else result

    @staticmethod
    def base_to_int(s: str, base: int) -> int:
        """任意进制（2-36）字符串转整数。

        :param s: 进制字符串
        :param base: 原进制（2-36）
        :return: 整数
        """
        return int(s, base)

    @staticmethod
    def format_bytes(size: float, decimals: int = 2) -> str:
        """字节大小格式化为人类可读单位（B/KB/MB/GB/TB/PB）。

        :param size: 字节数
        :param decimals: 保留小数位数
        :return: 可读字符串
        """
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        value = float(size)
        index = 0
        while value >= 1024 and index < len(units) - 1:
            value /= 1024
            index += 1
        if index == 0:
            return f"{int(value)}{units[index]}"
        return f"{value:.{decimals}f}{units[index]}"
