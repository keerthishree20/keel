"""The syntax tree. Both engines start from exactly this."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Node:
    line: int


# ---------------------------------------------------------------- expressions

@dataclass(slots=True)
class Literal(Node):
    value: object


@dataclass(slots=True)
class Name(Node):
    name: str


@dataclass(slots=True)
class Assign(Node):
    name: str
    value: Node


@dataclass(slots=True)
class Unary(Node):
    op: str
    operand: Node


@dataclass(slots=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass(slots=True)
class Logical(Node):
    op: str           # "and" or "or", which short-circuit
    left: Node
    right: Node


@dataclass(slots=True)
class Call(Node):
    callee: Node
    args: list[Node]


@dataclass(slots=True)
class ListLiteral(Node):
    items: list[Node]


@dataclass(slots=True)
class Index(Node):
    target: Node
    index: Node


@dataclass(slots=True)
class IndexAssign(Node):
    target: Node
    index: Node
    value: Node


@dataclass(slots=True)
class Function(Node):
    name: str
    params: list[str]
    body: list[Node]


# ----------------------------------------------------------------- statements

@dataclass(slots=True)
class ExprStmt(Node):
    expr: Node


@dataclass(slots=True)
class Let(Node):
    name: str
    value: Node | None


@dataclass(slots=True)
class FnDecl(Node):
    function: Function


@dataclass(slots=True)
class Block(Node):
    body: list[Node] = field(default_factory=list)


@dataclass(slots=True)
class If(Node):
    condition: Node
    then: Node
    otherwise: Node | None


@dataclass(slots=True)
class While(Node):
    condition: Node
    body: Node


@dataclass(slots=True)
class Return(Node):
    value: Node | None


@dataclass(slots=True)
class Program:
    body: list[Node]
