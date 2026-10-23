"""规则算式：白名单表达式，不用 eval。数字一律用 Decimal，避免向上取整时的浮点误差。"""
import ast
import math
import operator
from decimal import ROUND_HALF_UP, Decimal

from ..i18n import tr


class ExprError(ValueError):
    pass


def num(value):
    """输入、参数统一转成 Decimal；字符串和列表原样（列表内的数字也转）。"""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, (list, tuple)):
        return [num(v) for v in value]
    return value


def _round(x, n=0):
    return x.quantize(Decimal(1).scaleb(-int(n)), rounding=ROUND_HALF_UP)


FUNCS = {
    "ceil": lambda x: Decimal(math.ceil(x)),
    "floor": lambda x: Decimal(math.floor(x)),
    "round": _round,
    "min": min,
    "max": max,
    "abs": abs,
}
CONSTS = {"pi": Decimal("3.14159265358979323846")}

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
        ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
_ALLOWED = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp, ast.IfExp, ast.Call,
            ast.Name, ast.Constant, ast.Load, ast.And, ast.Or, *_BIN, *_CMP, *_UNARY)


def parse(text: str) -> ast.Expression:
    """解析并检查算式，只允许四则运算、比较、条件、白名单函数。"""
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError:
        raise ExprError(tr("算式写法有误：", "Formula syntax error: ") + text)
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise ExprError(tr("算式里不允许用：", "Not allowed in a formula: ") + type(node).__name__)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
                raise ExprError(tr("只能用这些函数：", "Only these functions are allowed: ") + ", ".join(FUNCS))
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, str, bool)):
            raise ExprError(tr("算式里只能写数字或文字", "Only numbers or text are allowed in a formula"))
    return tree


def names(tree: ast.Expression) -> set[str]:
    """算式引用到的输入 / 参数 / 前面规则结果的名称。"""
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(FUNCS) - set(CONSTS)


def evaluate(tree: ast.Expression, ctx: dict):
    def ev(node):
        match node:
            case ast.Expression(body=body):
                return ev(body)
            case ast.Constant(value=v):
                return num(v)
            case ast.Name(id=name):
                if name in CONSTS:
                    return CONSTS[name]
                return ctx[name]
            case ast.BinOp(left=l, op=op, right=r):
                try:
                    return _BIN[type(op)](ev(l), ev(r))
                except ArithmeticError:
                    raise ExprError(tr("计算出错（例如除以 0）", "Calculation error (e.g. division by 0)"))
            case ast.UnaryOp(op=op, operand=x):
                return _UNARY[type(op)](ev(x))
            case ast.Compare(left=left, ops=ops, comparators=rest):
                a = ev(left)
                for op, c in zip(ops, rest):
                    b = ev(c)
                    if not _CMP[type(op)](a, b):
                        return False
                    a = b
                return True
            case ast.BoolOp(op=ast.And(), values=vals):
                return all(ev(v) for v in vals)
            case ast.BoolOp(op=ast.Or(), values=vals):
                return any(ev(v) for v in vals)
            case ast.IfExp(test=t, body=b, orelse=o):
                return ev(b) if ev(t) else ev(o)
            case ast.Call(func=ast.Name(id=fn), args=args):
                return FUNCS[fn](*[ev(a) for a in args])
        raise ExprError(tr("不支持：", "Not supported: ") + ast.dump(node))

    return ev(tree)


def fmt(value) -> str:
    """展开算式时显示的数值：一万以上加千分位，小数最多 4 位。"""
    if isinstance(value, list):
        return "[" + ", ".join(fmt(v) for v in value) + "]"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return f"{int(value):,}" if abs(value) >= 10000 else str(int(value))
        return f"{_round(value, 4).normalize():,f}" if abs(value) >= 10000 else f"{_round(value, 4).normalize():f}"
    return str(value)


def substitute(tree: ast.Expression, ctx: dict) -> str:
    """把算式里的名称换成实际数值，例如 ceil(power_kw / circuit_kw) → ceil(5.7344 / 2.5)。"""
    class Sub(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in ctx:
                return ast.copy_location(ast.Name(id=fmt(ctx[node.id])), node)
            return node

    return ast.unparse(Sub().visit(ast.parse(ast.unparse(tree), mode="eval")))
