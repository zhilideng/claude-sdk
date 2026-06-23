"""用于验证 MCP 完整调用链路的安全计算工具。"""

from typing import Literal

from pydantic import BaseModel

CalculationOperator = Literal["add", "subtract", "multiply", "divide"]
MAX_ABSOLUTE_VALUE = 1_000_000_000_000


class CalculationResult(BaseModel):
    """计算工具的结构化输出。"""

    a: float
    b: float
    operator: CalculationOperator
    result: float


def calculate(a: float, b: float, operator: CalculationOperator) -> CalculationResult:
    """执行受限四则运算，不使用动态表达式求值。"""
    if abs(a) > MAX_ABSOLUTE_VALUE or abs(b) > MAX_ABSOLUTE_VALUE:
        raise ValueError(f"数值必须位于 ±{MAX_ABSOLUTE_VALUE} 范围内")

    operations = {
        "add": lambda: a + b,
        "subtract": lambda: a - b,
        "multiply": lambda: a * b,
        "divide": lambda: a / b,
    }
    if operator not in operations:
        raise ValueError(f"不支持的运算符: {operator}")
    if operator == "divide" and b == 0:
        raise ValueError("除数不能为零")

    return CalculationResult(a=a, b=b, operator=operator, result=operations[operator]())
