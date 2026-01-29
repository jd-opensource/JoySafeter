#!/usr/bin/env python
# coding=utf-8
"""
AST Evaluator - Core Python AST interpreter for CodeAgent.

This module implements a secure Python AST interpreter that evaluates code
with restricted access to imports and built-in functions. adapted for DeepAgents.

Key features:
- Recursive AST evaluation supporting 30+ node types
- Security controls (operation counting, import restrictions)
- State persistence across executions
- Tool injection as callable functions
"""

import ast
import builtins
import difflib
import math
from collections.abc import Callable, Generator, Mapping
from functools import wraps
from importlib import import_module
from types import ModuleType
from typing import Any, Optional

from loguru import logger

from .security import (
    BASE_BUILTIN_MODULES,
    InterpreterError,
    check_import_authorized,
    check_safer_result,
)

# Error types that can be raised in user code
ERRORS = {
    name: getattr(builtins, name)
    for name in dir(builtins)
    if isinstance(getattr(builtins, name), type) and issubclass(getattr(builtins, name), BaseException)
}

# Limits
MAX_OPERATIONS = 10_000_000
MAX_WHILE_ITERATIONS = 1_000_000

# Allowed dunder methods
ALLOWED_DUNDER_METHODS = ["__init__", "__str__", "__repr__"]


def custom_print(*args):
    """Custom print that does nothing - output is captured separately."""
    return None


def nodunder_getattr(obj, name, default=None):
    """Safe getattr that blocks dunder attributes."""
    if name.startswith("__") and name.endswith("__"):
        raise InterpreterError(f"Forbidden access to dunder attribute: {name}")
    return getattr(obj, name, default)


# Base Python tools available in the interpreter
BASE_PYTHON_TOOLS = {
    "print": custom_print,
    "isinstance": isinstance,
    "range": range,
    "float": float,
    "int": int,
    "bool": bool,
    "str": str,
    "set": set,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "round": round,
    "ceil": math.ceil,
    "floor": math.floor,
    "log": math.log,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "degrees": math.degrees,
    "radians": math.radians,
    "pow": pow,
    "sqrt": math.sqrt,
    "len": len,
    "sum": sum,
    "max": max,
    "min": min,
    "abs": abs,
    "enumerate": enumerate,
    "zip": zip,
    "reversed": reversed,
    "sorted": sorted,
    "all": all,
    "any": any,
    "map": map,
    "filter": filter,
    "ord": ord,
    "chr": chr,
    "next": next,
    "iter": iter,
    "divmod": divmod,
    "callable": callable,
    "getattr": nodunder_getattr,
    "hasattr": hasattr,
    "setattr": setattr,
    "issubclass": issubclass,
    "type": type,
    "complex": complex,
    "bytes": bytes,
    "bytearray": bytearray,
    "memoryview": memoryview,
    "frozenset": frozenset,
    "slice": slice,
    "object": object,
    "hex": hex,
    "oct": oct,
    "bin": bin,
    "format": format,
    "repr": repr,
    "hash": hash,
    "id": id,
    "input": lambda *args: "",  # Disabled for safety
    "open": None,  # Will be overridden if file access is allowed
}


class PrintContainer:
    """Container for capturing print outputs."""

    def __init__(self):
        self.value = ""

    def append(self, text):
        self.value += text
        return self

    def __iadd__(self, other):
        self.value += str(other)
        return self

    def __str__(self):
        return self.value

    def __repr__(self):
        return f"PrintContainer({self.value})"

    def __len__(self):
        return len(self.value)


class BreakException(Exception):
    """Exception for break statement."""

    pass


class ContinueException(Exception):
    """Exception for continue statement."""

    pass


class ReturnException(Exception):
    """Exception for return statement."""

    def __init__(self, value):
        self.value = value


def get_iterable(obj):
    """Get iterable from an object."""
    if isinstance(obj, list):
        return obj
    elif hasattr(obj, "__iter__"):
        return list(obj)
    else:
        raise InterpreterError("Object is not iterable")


def safer_eval(func: Callable):
    """Decorator to enhance security by checking return values."""

    @wraps(func)
    def _check_return(
        expression,
        state,
        static_tools,
        custom_tools,
        authorized_imports=BASE_BUILTIN_MODULES,
    ):
        result = func(expression, state, static_tools, custom_tools, authorized_imports=authorized_imports)
        check_safer_result(result, static_tools, authorized_imports)
        return result

    return _check_return


def safer_func(
    func: Callable,
    static_tools: Optional[dict[str, Callable]] = None,
    authorized_imports: Optional[list[str]] = None,
):
    """Decorator to enhance security of function calls."""
    if static_tools is None:
        static_tools = BASE_PYTHON_TOOLS  # type: ignore[assignment]
    if authorized_imports is None:
        authorized_imports = BASE_BUILTIN_MODULES

    if isinstance(func, type):
        return func

    @wraps(func)
    def _check_return(*args, **kwargs):
        result = func(*args, **kwargs)
        check_safer_result(result, static_tools, authorized_imports)
        return result

    return _check_return


def build_import_tree(authorized_imports: list[str]) -> dict[str, Any]:
    """Build a tree structure from authorized imports for efficient lookup."""
    tree: dict[str, Any] = {}
    for import_path in authorized_imports:
        parts = import_path.split(".")
        current = tree
        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]
    return tree


def get_safe_module(raw_module, authorized_imports, visited=None):
    """Create a safe copy of a module."""
    if not isinstance(raw_module, ModuleType):
        return raw_module

    if visited is None:
        visited = set()

    module_id = id(raw_module)
    if module_id in visited:
        return raw_module
    visited.add(module_id)

    safe_module = ModuleType(raw_module.__name__)

    for attr_name in dir(raw_module):
        try:
            attr_value = getattr(raw_module, attr_name)
        except (ImportError, AttributeError) as e:
            logger.debug(f"Skipping {raw_module.__name__}.{attr_name}: {e}")
            continue

        if isinstance(attr_value, ModuleType):
            attr_value = get_safe_module(attr_value, authorized_imports, visited=visited)
        setattr(safe_module, attr_name, attr_value)

    return safe_module


# ============================================================================
# AST Evaluation Functions
# ============================================================================


def evaluate_attribute(
    expression: ast.Attribute,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate attribute access."""
    if expression.attr.startswith("__") and expression.attr.endswith("__"):
        raise InterpreterError(f"Forbidden access to dunder attribute: {expression.attr}")
    value = evaluate_ast(expression.value, state, static_tools, custom_tools, authorized_imports)
    return getattr(value, expression.attr)


def evaluate_unaryop(
    expression: ast.UnaryOp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate unary operations."""
    operand = evaluate_ast(expression.operand, state, static_tools, custom_tools, authorized_imports)
    if isinstance(expression.op, ast.USub):
        return -operand
    elif isinstance(expression.op, ast.UAdd):
        return operand
    elif isinstance(expression.op, ast.Not):
        return not operand
    elif isinstance(expression.op, ast.Invert):
        return ~operand
    else:
        raise InterpreterError(f"Unary operation {expression.op.__class__.__name__} is not supported.")


def evaluate_lambda(
    lambda_expression: ast.Lambda,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Callable:
    """Evaluate lambda expressions."""
    args = [arg.arg for arg in lambda_expression.args.args]

    def lambda_func(*values: Any) -> Any:
        new_state = state.copy()
        for arg, value in zip(args, values):
            new_state[arg] = value
        return evaluate_ast(
            lambda_expression.body,
            new_state,
            static_tools,
            custom_tools,
            authorized_imports,
        )

    return lambda_func


def evaluate_while(
    while_loop: ast.While,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Evaluate while loops."""
    iterations = 0
    while evaluate_ast(while_loop.test, state, static_tools, custom_tools, authorized_imports):
        for node in while_loop.body:
            try:
                evaluate_ast(node, state, static_tools, custom_tools, authorized_imports)
            except BreakException:
                return None
            except ContinueException:
                break
        iterations += 1
        if iterations > MAX_WHILE_ITERATIONS:
            raise InterpreterError(f"Maximum number of {MAX_WHILE_ITERATIONS} iterations in While loop exceeded")
    return None


def create_function(
    func_def: ast.FunctionDef,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Callable:
    """Create a function from a FunctionDef AST node."""
    source_code = ast.unparse(func_def)

    def new_func(*args: Any, **kwargs: Any) -> Any:
        func_state = state.copy()
        arg_names = [arg.arg for arg in func_def.args.args]
        default_values = [
            evaluate_ast(d, state, static_tools, custom_tools, authorized_imports) for d in func_def.args.defaults
        ]

        defaults = dict(zip(arg_names[-len(default_values) :], default_values)) if default_values else {}

        for name, value in zip(arg_names, args):
            func_state[name] = value

        for name, value in kwargs.items():
            func_state[name] = value

        if func_def.args.vararg:
            func_state[func_def.args.vararg.arg] = args[len(arg_names) :]

        if func_def.args.kwarg:
            func_state[func_def.args.kwarg.arg] = kwargs

        for name, value in defaults.items():
            if name not in func_state:
                func_state[name] = value

        if func_def.args.args and func_def.args.args[0].arg == "self":
            if args:
                func_state["self"] = args[0]
                func_state["__class__"] = args[0].__class__

        result = None
        try:
            for stmt in func_def.body:
                result = evaluate_ast(stmt, func_state, static_tools, custom_tools, authorized_imports)
        except ReturnException as e:
            result = e.value

        if func_def.name == "__init__":
            return None
        return result

    new_func.__ast__ = func_def  # type: ignore[attr-defined]
    new_func.__source__ = source_code  # type: ignore[attr-defined]
    new_func.__name__ = func_def.name
    return new_func


def evaluate_function_def(
    func_def: ast.FunctionDef,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Callable:
    """Evaluate function definitions."""
    custom_tools[func_def.name] = create_function(func_def, state, static_tools, custom_tools, authorized_imports)
    return custom_tools[func_def.name]


def evaluate_class_def(
    class_def: ast.ClassDef,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> type:
    """Evaluate class definitions."""
    class_name = class_def.name
    bases = [evaluate_ast(base, state, static_tools, custom_tools, authorized_imports) for base in class_def.bases]

    metaclass: type = type
    for base in bases:
        base_metaclass = type(base)
        if base_metaclass is not type:
            metaclass = base_metaclass  # type: ignore[assignment]
            break

    if hasattr(metaclass, "__prepare__"):
        class_dict = metaclass.__prepare__(class_name, tuple(bases))  # type: ignore[arg-type]
    else:
        class_dict = {}

    for stmt in class_def.body:
        if isinstance(stmt, ast.FunctionDef):
            class_dict[stmt.name] = evaluate_ast(stmt, state, static_tools, custom_tools, authorized_imports)
        elif isinstance(stmt, ast.AnnAssign):
            if stmt.value:
                value = evaluate_ast(stmt.value, state, static_tools, custom_tools, authorized_imports)
                if isinstance(stmt.target, ast.Name):
                    class_dict[stmt.target.id] = value
        elif isinstance(stmt, ast.Assign):
            value = evaluate_ast(stmt.value, state, static_tools, custom_tools, authorized_imports)
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    class_dict[target.id] = value
        elif isinstance(stmt, ast.Pass):
            pass
        elif isinstance(stmt, ast.Expr) and stmt == class_def.body[0]:
            if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                class_dict["__doc__"] = stmt.value.value

    new_class = metaclass(class_name, tuple(bases), class_dict)  # type: ignore[call-overload]
    state[class_name] = new_class
    return new_class  # type: ignore[no-any-return]


def evaluate_annassign(
    annassign: ast.AnnAssign,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate annotated assignments."""
    if annassign.value:
        value = evaluate_ast(annassign.value, state, static_tools, custom_tools, authorized_imports)
        set_value(annassign.target, value, state, static_tools, custom_tools, authorized_imports)
        return value
    return None


def evaluate_augassign(
    expression: ast.AugAssign,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate augmented assignments (+=, -=, etc.)."""

    def get_current_value(target: ast.AST) -> Any:
        if isinstance(target, ast.Name):
            return state.get(target.id, 0)
        elif isinstance(target, ast.Subscript):
            obj = evaluate_ast(target.value, state, static_tools, custom_tools, authorized_imports)
            key = evaluate_ast(target.slice, state, static_tools, custom_tools, authorized_imports)
            return obj[key]
        elif isinstance(target, ast.Attribute):
            obj = evaluate_ast(target.value, state, static_tools, custom_tools, authorized_imports)
            return getattr(obj, target.attr)
        else:
            raise InterpreterError(f"AugAssign not supported for {type(target)} targets.")

    current_value = get_current_value(expression.target)
    value_to_add = evaluate_ast(expression.value, state, static_tools, custom_tools, authorized_imports)

    op_map = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.BitAnd: lambda a, b: a & b,
        ast.BitOr: lambda a, b: a | b,
        ast.BitXor: lambda a, b: a ^ b,
        ast.LShift: lambda a, b: a << b,
        ast.RShift: lambda a, b: a >> b,
    }

    op_type = type(expression.op)
    if op_type in op_map:
        current_value = op_map[op_type](current_value, value_to_add)
    else:
        raise InterpreterError(f"Operation {op_type.__name__} is not supported.")

    set_value(expression.target, current_value, state, static_tools, custom_tools, authorized_imports)
    return current_value


def evaluate_boolop(
    node: ast.BoolOp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate boolean operations (and, or)."""
    is_short_circuit_value = (lambda x: not x) if isinstance(node.op, ast.And) else (lambda x: bool(x))

    for value in node.values:
        result = evaluate_ast(value, state, static_tools, custom_tools, authorized_imports)
        if is_short_circuit_value(result):
            return result
    return result


def evaluate_binop(
    binop: ast.BinOp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate binary operations."""
    left_val = evaluate_ast(binop.left, state, static_tools, custom_tools, authorized_imports)
    right_val = evaluate_ast(binop.right, state, static_tools, custom_tools, authorized_imports)

    op_map = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a**b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.BitAnd: lambda a, b: a & b,
        ast.BitOr: lambda a, b: a | b,
        ast.BitXor: lambda a, b: a ^ b,
        ast.LShift: lambda a, b: a << b,
        ast.RShift: lambda a, b: a >> b,
        ast.MatMult: lambda a, b: a @ b,
    }

    op_type = type(binop.op)
    if op_type in op_map:
        return op_map[op_type](left_val, right_val)
    else:
        raise NotImplementedError(f"Binary operation {op_type.__name__} is not implemented.")


def evaluate_assign(
    assign: ast.Assign,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate assignment statements."""
    result = evaluate_ast(assign.value, state, static_tools, custom_tools, authorized_imports)

    if len(assign.targets) == 1:
        set_value(assign.targets[0], result, state, static_tools, custom_tools, authorized_imports)
    else:
        for tgt in assign.targets:
            set_value(tgt, result, state, static_tools, custom_tools, authorized_imports)

    return result


def set_value(
    target: ast.AST,
    value: Any,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Set a value to a target."""
    if isinstance(target, ast.Name):
        if target.id in static_tools:
            raise InterpreterError(f"Cannot assign to name '{target.id}': this would erase the existing tool!")
        state[target.id] = value
    elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
        if not hasattr(value, "__iter__") or isinstance(value, (str, bytes)):
            raise InterpreterError("Cannot unpack non-iterable value")
        values = list(value)
        if len(target.elts) != len(values):
            raise InterpreterError("Cannot unpack: wrong number of values")
        for i, elem in enumerate(target.elts):
            set_value(elem, values[i], state, static_tools, custom_tools, authorized_imports)
    elif isinstance(target, ast.Subscript):
        obj = evaluate_ast(target.value, state, static_tools, custom_tools, authorized_imports)
        key = evaluate_ast(target.slice, state, static_tools, custom_tools, authorized_imports)
        obj[key] = value
    elif isinstance(target, ast.Attribute):
        obj = evaluate_ast(target.value, state, static_tools, custom_tools, authorized_imports)
        setattr(obj, target.attr, value)
    elif isinstance(target, ast.Starred):
        # Handle starred assignment (e.g., *rest = ...)
        set_value(target.value, value, state, static_tools, custom_tools, authorized_imports)
    else:
        raise InterpreterError(f"Cannot assign to {type(target).__name__}")


def evaluate_call(
    call: ast.Call,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate function calls."""
    func, func_name = None, None

    if isinstance(call.func, ast.Call):
        func = evaluate_ast(call.func, state, static_tools, custom_tools, authorized_imports)
    elif isinstance(call.func, ast.Lambda):
        func = evaluate_ast(call.func, state, static_tools, custom_tools, authorized_imports)
    elif isinstance(call.func, ast.Attribute):
        obj = evaluate_ast(call.func.value, state, static_tools, custom_tools, authorized_imports)
        func_name = call.func.attr
        if not hasattr(obj, func_name):
            raise InterpreterError(f"Object {obj} has no attribute {func_name}")
        func = getattr(obj, func_name)
    elif isinstance(call.func, ast.Name):
        func_name = call.func.id
        if func_name in state:
            func = state[func_name]
        elif func_name in static_tools:
            func = static_tools[func_name]
        elif func_name in custom_tools:
            func = custom_tools[func_name]
        elif func_name in ERRORS:
            func = ERRORS[func_name]
        else:
            raise InterpreterError(
                f"Forbidden function evaluation: '{func_name}' is not among the allowed tools or defined in preceding code"
            )
    elif isinstance(call.func, ast.Subscript):
        func = evaluate_ast(call.func, state, static_tools, custom_tools, authorized_imports)
    else:
        raise InterpreterError(f"This is not a correct function: {call.func}")

    if not callable(func):
        raise InterpreterError(f"This is not callable: {call.func}")

    # Evaluate arguments
    args = []
    for arg in call.args:
        if isinstance(arg, ast.Starred):
            args.extend(evaluate_ast(arg.value, state, static_tools, custom_tools, authorized_imports))
        else:
            args.append(evaluate_ast(arg, state, static_tools, custom_tools, authorized_imports))

    kwargs = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            starred_dict = evaluate_ast(keyword.value, state, static_tools, custom_tools, authorized_imports)
            if not isinstance(starred_dict, dict):
                raise InterpreterError(f"Cannot unpack non-dict value in **kwargs: {type(starred_dict).__name__}")
            kwargs.update(starred_dict)
        else:
            kwargs[keyword.arg] = evaluate_ast(keyword.value, state, static_tools, custom_tools, authorized_imports)

    # Handle special cases
    if func_name == "super":
        if not args:
            if "__class__" in state and "self" in state:
                return super(state["__class__"], state["self"])
            else:
                raise InterpreterError("super() needs at least one argument")
        cls = args[0]
        if len(args) == 1:
            return super(cls)
        elif len(args) == 2:
            return super(cls, args[1])
        else:
            raise InterpreterError("super() takes at most 2 arguments")
    elif func_name == "print":
        state["_print_outputs"] += " ".join(map(str, args)) + "\n"
        return None
    else:
        # Check for dangerous builtins
        import inspect

        if (inspect.getmodule(func) == builtins) and inspect.isbuiltin(func) and (func not in static_tools.values()):
            raise InterpreterError(
                f"Invoking a builtin function that has not been explicitly added as a tool is not allowed ({func_name})."
            )

        if (
            hasattr(func, "__name__")
            and func.__name__.startswith("__")
            and func.__name__.endswith("__")
            and (func.__name__ not in static_tools)
            and (func.__name__ not in ALLOWED_DUNDER_METHODS)
        ):
            raise InterpreterError(f"Forbidden call to dunder function: {func.__name__}")

        return func(*args, **kwargs)


def evaluate_subscript(
    subscript: ast.Subscript,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate subscript access."""
    index = evaluate_ast(subscript.slice, state, static_tools, custom_tools, authorized_imports)
    value = evaluate_ast(subscript.value, state, static_tools, custom_tools, authorized_imports)
    try:
        return value[index]
    except (KeyError, IndexError, TypeError) as e:
        error_message = f"Could not index {value} with '{index}': {type(e).__name__}: {e}"
        if isinstance(index, str) and isinstance(value, Mapping):
            close_matches = difflib.get_close_matches(index, list(value.keys()))
            if close_matches:
                error_message += f". Maybe you meant one of these indexes instead: {close_matches}"
        raise InterpreterError(error_message) from e


def evaluate_name(
    name: ast.Name,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate name lookup."""
    if name.id in state:
        return state[name.id]
    elif name.id in static_tools:
        return safer_func(static_tools[name.id], static_tools=static_tools, authorized_imports=authorized_imports)
    elif name.id in custom_tools:
        return custom_tools[name.id]
    elif name.id in ERRORS:
        return ERRORS[name.id]

    close_matches = difflib.get_close_matches(name.id, list(state.keys()))
    if close_matches:
        return state[close_matches[0]]
    raise InterpreterError(f"The variable `{name.id}` is not defined.")


def evaluate_condition(
    condition: ast.Compare,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> bool:
    """Evaluate comparison operations."""
    left = evaluate_ast(condition.left, state, static_tools, custom_tools, authorized_imports)

    for op, comparator in zip(condition.ops, condition.comparators):
        right = evaluate_ast(comparator, state, static_tools, custom_tools, authorized_imports)

        op_type = type(op)
        if op_type == ast.Eq:
            result = left == right
        elif op_type == ast.NotEq:
            result = left != right
        elif op_type == ast.Lt:
            result = left < right
        elif op_type == ast.LtE:
            result = left <= right
        elif op_type == ast.Gt:
            result = left > right
        elif op_type == ast.GtE:
            result = left >= right
        elif op_type == ast.Is:
            result = left is right
        elif op_type == ast.IsNot:
            result = left is not right
        elif op_type == ast.In:
            result = left in right
        elif op_type == ast.NotIn:
            result = left not in right
        else:
            raise InterpreterError(f"Unsupported comparison operator: {op_type}")

        if not result:
            return False
        left = right

    return True


def evaluate_if(
    if_statement: ast.If,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate if statements."""
    result = None
    test_result = evaluate_ast(if_statement.test, state, static_tools, custom_tools, authorized_imports)

    if test_result:
        for line in if_statement.body:
            result = evaluate_ast(line, state, static_tools, custom_tools, authorized_imports)
    else:
        for line in if_statement.orelse:
            result = evaluate_ast(line, state, static_tools, custom_tools, authorized_imports)

    return result


def evaluate_for(
    for_loop: ast.For,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Any:
    """Evaluate for loops."""
    result = None
    iterator = evaluate_ast(for_loop.iter, state, static_tools, custom_tools, authorized_imports)

    for counter in iterator:
        set_value(for_loop.target, counter, state, static_tools, custom_tools, authorized_imports)
        for node in for_loop.body:
            try:
                line_result = evaluate_ast(node, state, static_tools, custom_tools, authorized_imports)
                if line_result is not None:
                    result = line_result
            except BreakException:
                return result
            except ContinueException:
                break

    return result


def _evaluate_comprehensions(
    comprehensions: list[ast.comprehension],
    evaluate_element: Callable[[dict[str, Any]], Any],
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Generator[Any, None, None]:
    """Recursively evaluate nested comprehensions."""
    if not comprehensions:
        yield evaluate_element(state)
        return

    comprehension = comprehensions[0]
    iter_value = evaluate_ast(comprehension.iter, state, static_tools, custom_tools, authorized_imports)

    for value in iter_value:
        new_state = state.copy()
        set_value(comprehension.target, value, new_state, static_tools, custom_tools, authorized_imports)

        if all(
            evaluate_ast(if_clause, new_state, static_tools, custom_tools, authorized_imports)
            for if_clause in comprehension.ifs
        ):
            yield from _evaluate_comprehensions(
                comprehensions[1:], evaluate_element, new_state, static_tools, custom_tools, authorized_imports
            )


def evaluate_listcomp(
    listcomp: ast.ListComp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> list[Any]:
    """Evaluate list comprehensions."""
    return list(
        _evaluate_comprehensions(
            listcomp.generators,
            lambda comp_state: evaluate_ast(listcomp.elt, comp_state, static_tools, custom_tools, authorized_imports),
            state,
            static_tools,
            custom_tools,
            authorized_imports,
        )
    )


def evaluate_setcomp(
    setcomp: ast.SetComp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> set[Any]:
    """Evaluate set comprehensions."""
    return set(
        _evaluate_comprehensions(
            setcomp.generators,
            lambda comp_state: evaluate_ast(setcomp.elt, comp_state, static_tools, custom_tools, authorized_imports),
            state,
            static_tools,
            custom_tools,
            authorized_imports,
        )
    )


def evaluate_dictcomp(
    dictcomp: ast.DictComp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> dict[Any, Any]:
    """Evaluate dictionary comprehensions."""
    return dict(
        _evaluate_comprehensions(
            dictcomp.generators,
            lambda comp_state: (
                evaluate_ast(dictcomp.key, comp_state, static_tools, custom_tools, authorized_imports),
                evaluate_ast(dictcomp.value, comp_state, static_tools, custom_tools, authorized_imports),
            ),
            state,
            static_tools,
            custom_tools,
            authorized_imports,
        )
    )


def evaluate_try(
    try_node: ast.Try,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Evaluate try-except statements."""
    try:
        for stmt in try_node.body:
            evaluate_ast(stmt, state, static_tools, custom_tools, authorized_imports)
    except Exception as e:
        matched = False
        for handler in try_node.handlers:
            if handler.type is None or isinstance(
                e,
                evaluate_ast(handler.type, state, static_tools, custom_tools, authorized_imports),
            ):
                matched = True
                if handler.name:
                    state[handler.name] = e
                for stmt in handler.body:
                    evaluate_ast(stmt, state, static_tools, custom_tools, authorized_imports)
                break
        if not matched:
            raise e
    else:
        if try_node.orelse:
            for stmt in try_node.orelse:
                evaluate_ast(stmt, state, static_tools, custom_tools, authorized_imports)
    finally:
        if try_node.finalbody:
            for stmt in try_node.finalbody:
                evaluate_ast(stmt, state, static_tools, custom_tools, authorized_imports)


def evaluate_raise(
    raise_node: ast.Raise,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Evaluate raise statements."""
    if raise_node.exc is not None:
        exc = evaluate_ast(raise_node.exc, state, static_tools, custom_tools, authorized_imports)
    else:
        exc = None

    if raise_node.cause is not None:
        cause = evaluate_ast(raise_node.cause, state, static_tools, custom_tools, authorized_imports)
    else:
        cause = None

    if exc is not None:
        if cause is not None:
            raise exc from cause
        else:
            raise exc
    else:
        raise InterpreterError("Re-raise is not supported without an active exception")


def evaluate_assert(
    assert_node: ast.Assert,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Evaluate assert statements."""
    test_result = evaluate_ast(assert_node.test, state, static_tools, custom_tools, authorized_imports)
    if not test_result:
        if assert_node.msg:
            msg = evaluate_ast(assert_node.msg, state, static_tools, custom_tools, authorized_imports)
            raise AssertionError(msg)
        else:
            test_code = ast.unparse(assert_node.test)
            raise AssertionError(f"Assertion failed: {test_code}")


def evaluate_with(
    with_node: ast.With,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Evaluate with statements."""
    contexts = []
    for item in with_node.items:
        context_expr = evaluate_ast(item.context_expr, state, static_tools, custom_tools, authorized_imports)
        if item.optional_vars:
            if isinstance(item.optional_vars, ast.Name):
                state[item.optional_vars.id] = context_expr.__enter__()
                contexts.append(state[item.optional_vars.id])
            else:
                # Handle other types of optional_vars
                var_name = getattr(item.optional_vars, "id", None)
                if var_name:
                    state[var_name] = context_expr.__enter__()
                    contexts.append(state[var_name])
        else:
            context_var = context_expr.__enter__()
            contexts.append(context_var)

    try:
        for stmt in with_node.body:
            evaluate_ast(stmt, state, static_tools, custom_tools, authorized_imports)
    except Exception as e:
        for context in reversed(contexts):
            context.__exit__(type(e), e, e.__traceback__)
        raise
    else:
        for context in reversed(contexts):
            context.__exit__(None, None, None)


def evaluate_import(expression, state, authorized_imports):
    """Evaluate import statements."""
    if isinstance(expression, ast.Import):
        for alias in expression.names:
            if check_import_authorized(alias.name, authorized_imports):
                raw_module = import_module(alias.name)
                state[alias.asname or alias.name] = get_safe_module(raw_module, authorized_imports)
            else:
                raise InterpreterError(
                    f"Import of {alias.name} is not allowed. Authorized imports are: {authorized_imports}"
                )
        return None
    elif isinstance(expression, ast.ImportFrom):
        if check_import_authorized(expression.module, authorized_imports):
            raw_module = __import__(expression.module, fromlist=[alias.name for alias in expression.names])
            module = get_safe_module(raw_module, authorized_imports)

            if expression.names[0].name == "*":
                if hasattr(module, "__all__"):
                    for name in module.__all__:
                        state[name] = getattr(module, name)
                else:
                    for name in dir(module):
                        if not name.startswith("_"):
                            state[name] = getattr(module, name)
            else:
                for alias in expression.names:
                    if hasattr(module, alias.name):
                        state[alias.asname or alias.name] = getattr(module, alias.name)
                    else:
                        raise InterpreterError(f"Module {expression.module} has no attribute {alias.name}")
        else:
            raise InterpreterError(
                f"Import from {expression.module} is not allowed. Authorized imports are: {authorized_imports}"
            )
        return None


def evaluate_generatorexp(
    genexp: ast.GeneratorExp,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> Generator[Any, None, None]:
    """Evaluate generator expressions."""

    def generator():
        for gen in genexp.generators:
            iter_value = evaluate_ast(gen.iter, state, static_tools, custom_tools, authorized_imports)
            for value in iter_value:
                new_state = state.copy()
                set_value(gen.target, value, new_state, static_tools, custom_tools, authorized_imports)
                if all(
                    evaluate_ast(if_clause, new_state, static_tools, custom_tools, authorized_imports)
                    for if_clause in gen.ifs
                ):
                    yield evaluate_ast(genexp.elt, new_state, static_tools, custom_tools, authorized_imports)

    return generator()  # type: ignore[no-any-return]


def evaluate_delete(
    delete_node: ast.Delete,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """Evaluate delete statements."""
    for target in delete_node.targets:
        if isinstance(target, ast.Name):
            if target.id in state:
                del state[target.id]
            else:
                raise InterpreterError(f"Cannot delete name '{target.id}': name is not defined")
        elif isinstance(target, ast.Subscript):
            obj = evaluate_ast(target.value, state, static_tools, custom_tools, authorized_imports)
            index = evaluate_ast(target.slice, state, static_tools, custom_tools, authorized_imports)
            try:
                del obj[index]
            except (TypeError, KeyError, IndexError) as e:
                raise InterpreterError(f"Cannot delete index/key: {e}")
        else:
            raise InterpreterError(f"Deletion of {type(target).__name__} targets is not supported")


@safer_eval
def evaluate_ast(
    expression: ast.AST,
    state: dict[str, Any],
    static_tools: dict[str, Callable],
    custom_tools: dict[str, Callable],
    authorized_imports: Optional[list[str]] = None,
) -> Any:
    """
    Evaluate an abstract syntax tree using the content of the variables stored in a state
    and only evaluating a given set of functions.

    Args:
        expression: The AST node to evaluate.
        state: A dictionary mapping variable names to values.
        static_tools: Functions that may be called (cannot be overwritten).
        custom_tools: Functions that may be called (can be overwritten).
        authorized_imports: List of modules that can be imported.

    Returns:
        The result of evaluating the expression.
    """
    if authorized_imports is None:
        authorized_imports = BASE_BUILTIN_MODULES

    # Check operation count
    if state.setdefault("_operations_count", {"counter": 0})["counter"] >= MAX_OPERATIONS:
        raise InterpreterError(
            f"Reached the max number of operations of {MAX_OPERATIONS}. "
            "Maybe there is an infinite loop somewhere in the code."
        )
    state["_operations_count"]["counter"] += 1

    common_params = (state, static_tools, custom_tools, authorized_imports)

    # Assignment nodes
    if isinstance(expression, ast.Assign):
        return evaluate_assign(expression, *common_params)
    elif isinstance(expression, ast.AnnAssign):
        return evaluate_annassign(expression, *common_params)
    elif isinstance(expression, ast.AugAssign):
        return evaluate_augassign(expression, *common_params)

    # Call nodes
    elif isinstance(expression, ast.Call):
        return evaluate_call(expression, *common_params)

    # Literal nodes
    elif isinstance(expression, ast.Constant):
        return expression.value
    elif isinstance(expression, ast.Tuple):
        return tuple(evaluate_ast(elt, *common_params) for elt in expression.elts)
    elif isinstance(expression, ast.List):
        return [evaluate_ast(elt, *common_params) for elt in expression.elts]
    elif isinstance(expression, ast.Dict):
        keys = (evaluate_ast(k, *common_params) for k in expression.keys)
        values = (evaluate_ast(v, *common_params) for v in expression.values)
        return dict(zip(keys, values))
    elif isinstance(expression, ast.Set):
        return set(evaluate_ast(elt, *common_params) for elt in expression.elts)

    # Comprehensions
    elif isinstance(expression, ast.GeneratorExp):
        return evaluate_generatorexp(expression, *common_params)
    elif isinstance(expression, ast.ListComp):
        return evaluate_listcomp(expression, *common_params)
    elif isinstance(expression, ast.DictComp):
        return evaluate_dictcomp(expression, *common_params)
    elif isinstance(expression, ast.SetComp):
        return evaluate_setcomp(expression, *common_params)

    # Operations
    elif isinstance(expression, ast.UnaryOp):
        return evaluate_unaryop(expression, *common_params)
    elif isinstance(expression, ast.BoolOp):
        return evaluate_boolop(expression, *common_params)
    elif isinstance(expression, ast.BinOp):
        return evaluate_binop(expression, *common_params)
    elif isinstance(expression, ast.Compare):
        return evaluate_condition(expression, *common_params)

    # Control flow
    elif isinstance(expression, ast.Break):
        raise BreakException()
    elif isinstance(expression, ast.Continue):
        raise ContinueException()
    elif isinstance(expression, ast.Return):
        raise ReturnException(evaluate_ast(expression.value, *common_params) if expression.value else None)
    elif isinstance(expression, ast.Pass):
        return None

    # Functions and lambdas
    elif isinstance(expression, ast.Lambda):
        return evaluate_lambda(expression, *common_params)
    elif isinstance(expression, ast.FunctionDef):
        return evaluate_function_def(expression, *common_params)

    # Expressions and names
    elif isinstance(expression, ast.Expr):
        return evaluate_ast(expression.value, *common_params)
    elif isinstance(expression, ast.Name):
        return evaluate_name(expression, *common_params)
    elif isinstance(expression, ast.Attribute):
        return evaluate_attribute(expression, *common_params)
    elif isinstance(expression, ast.Subscript):
        return evaluate_subscript(expression, *common_params)
    elif isinstance(expression, ast.Starred):
        return evaluate_ast(expression.value, *common_params)

    # Control structures
    elif isinstance(expression, ast.For):
        return evaluate_for(expression, *common_params)
    elif isinstance(expression, ast.While):
        return evaluate_while(expression, *common_params)
    elif isinstance(expression, ast.If):
        return evaluate_if(expression, *common_params)
    elif isinstance(expression, ast.IfExp):
        test_val = evaluate_ast(expression.test, *common_params)
        if test_val:
            return evaluate_ast(expression.body, *common_params)
        else:
            return evaluate_ast(expression.orelse, *common_params)

    # Formatted strings
    elif isinstance(expression, ast.FormattedValue):
        value = evaluate_ast(expression.value, *common_params)
        if not expression.format_spec:
            return value
        format_spec = evaluate_ast(expression.format_spec, *common_params)
        return format(value, format_spec)
    elif isinstance(expression, ast.JoinedStr):
        return "".join(str(evaluate_ast(v, *common_params)) for v in expression.values)

    # Slices
    elif isinstance(expression, ast.Slice):
        return slice(
            evaluate_ast(expression.lower, *common_params) if expression.lower else None,
            evaluate_ast(expression.upper, *common_params) if expression.upper else None,
            evaluate_ast(expression.step, *common_params) if expression.step else None,
        )

    # Imports
    elif isinstance(expression, (ast.Import, ast.ImportFrom)):
        return evaluate_import(expression, state, authorized_imports)

    # Classes
    elif isinstance(expression, ast.ClassDef):
        return evaluate_class_def(expression, *common_params)

    # Exception handling
    elif isinstance(expression, ast.Try):
        return evaluate_try(expression, *common_params)
    elif isinstance(expression, ast.Raise):
        return evaluate_raise(expression, *common_params)
    elif isinstance(expression, ast.Assert):
        return evaluate_assert(expression, *common_params)

    # With statements
    elif isinstance(expression, ast.With):
        return evaluate_with(expression, *common_params)

    # Delete
    elif isinstance(expression, ast.Delete):
        return evaluate_delete(expression, *common_params)

    # Legacy Python 3.8 Index node
    elif hasattr(ast, "Index") and isinstance(expression, ast.Index):
        value = getattr(expression, "value", None)
        if value is not None:
            return evaluate_ast(value, *common_params)
        raise InterpreterError("Index node has no value attribute")

    else:
        raise InterpreterError(f"{expression.__class__.__name__} is not supported.")


__all__ = ["evaluate_ast", "BASE_PYTHON_TOOLS", "PrintContainer", "MAX_OPERATIONS", "MAX_WHILE_ITERATIONS"]
