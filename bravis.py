#!/usr/bin/env python3
"""
bra-vis v0.3
Branch Visibility for xmeta Relative Taxonomy Shorthand (RTS).

RTS basics:
  :    descend one level
  ::   descend two unnamed/inferred levels
  :::  descend three unnamed/inferred levels

  |    ascend one level
  ||   ascend two levels
  |||  ascend three levels

  ,    add siblings at the current level
  ""   quoted node literal

Official behavior:
  - Sibling lists are payloads under the current branch.
  - After `mammalia:primates,carnivora`, cursor remains at `mammalia` if an ascend follows.
  - If ascent goes above known ancestry, visible `unknown` ancestor nodes are created.
  - Operators can chain before a node: `|||:::cetacea` means ascend 3, descend 3, then add cetacea.
  - Descending through unnamed levels uses a known indexed path only when it is unambiguous.
  - If no safe indexed path exists, unnamed descent creates visible `unknown` placeholders.
  - Known unquoted node names are indexed for later re-entry.
  - Quoted nodes are literal payload data and are not structural anchors.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class TokenKind(Enum):
    NODE = auto()
    DESCEND = auto()
    ASCEND = auto()
    SIBLING = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    quoted: bool = False


@dataclass(frozen=True)
class Move:
    kind: TokenKind
    depth: int


@dataclass
class Node:
    name: str
    parent: Optional["Node"] = None
    children: List["Node"] = field(default_factory=list)
    quoted: bool = False

    def add_child(self, name: str, quoted: bool = False) -> "Node":
        name = clean_name(name)
        for child in self.children:
            if child.name == name and child.quoted == quoted:
                return child
        child = Node(name=name, parent=self, quoted=quoted)
        self.children.append(child)
        return child

    def detach_child(self, child: "Node") -> None:
        self.children.remove(child)
        child.parent = None

    def add_existing_child(self, child: "Node") -> None:
        if child not in self.children:
            self.children.append(child)
        child.parent = self


def clean_name(value: str) -> str:
    value = value.strip()
    return value if value else "unknown"


def tokenize(expr: str) -> List[Token]:
    tokens: List[Token] = []
    buf: List[str] = []
    in_quote = False
    escaped = False
    buf_quoted = False

    def flush_node() -> None:
        nonlocal buf, buf_quoted
        if not buf:
            return
        value = "".join(buf).strip()
        buf = []
        if value:
            tokens.append(Token(TokenKind.NODE, value, quoted=buf_quoted))
        buf_quoted = False

    i = 0
    while i < len(expr):
        ch = expr[i]

        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue

        if in_quote and ch == "\\":
            escaped = True
            i += 1
            continue

        if ch == '"':
            if not in_quote and not buf:
                buf_quoted = True
            in_quote = not in_quote
            i += 1
            continue

        if in_quote:
            buf.append(ch)
            i += 1
            continue

        if ch in ":|,":
            flush_node()

            if ch == ",":
                tokens.append(Token(TokenKind.SIBLING, ","))
                i += 1
                continue

            start = i
            while i + 1 < len(expr) and expr[i + 1] == ch:
                i += 1
            op = expr[start : i + 1]
            kind = TokenKind.DESCEND if ch == ":" else TokenKind.ASCEND
            tokens.append(Token(kind, op))
            i += 1
            continue

        buf.append(ch)
        i += 1

    if in_quote:
        raise ValueError("unclosed quote in RTS expression")

    flush_node()
    return tokens


class Parser:
    def __init__(self) -> None:
        self.root = Node("__ROOT__")
        self.current = self.root
        self.index: Dict[str, Node] = {}
        self.moves: List[Move] = []

    def parse(self, expr: str) -> Node:
        tokens = tokenize(expr)

        for i, token in enumerate(tokens):
            next_kind = self._next_kind(tokens, i)

            if token.kind == TokenKind.NODE:
                self._add_node(token.value, token.quoted, next_kind)
            elif token.kind == TokenKind.DESCEND:
                self.moves.append(Move(TokenKind.DESCEND, len(token.value)))
            elif token.kind == TokenKind.ASCEND:
                self.moves.append(Move(TokenKind.ASCEND, len(token.value)))
            elif token.kind == TokenKind.SIBLING:
                self.moves.append(Move(TokenKind.SIBLING, 1))

        return self.root

    @staticmethod
    def _next_kind(tokens: List[Token], index: int) -> Optional[TokenKind]:
        if index + 1 >= len(tokens):
            return None
        return tokens[index + 1].kind

    def _add_node(self, name: str, quoted: bool, next_kind: Optional[TokenKind]) -> None:
        original_moves = list(self.moves)
        parent = self._resolve_parent_for_next_node(name, quoted)
        node = self._add_or_reenter(parent, name, quoted, prefer_existing=self._should_reenter(original_moves, quoted))

        self.moves.clear()

        # Branch-construction cursor rule:
        # If a payload child/sibling list is immediately followed by ascent, keep the cursor on its branch parent.
        # Example: mammalia:primates,carnivora|||plantae ascends from mammalia.
        if next_kind == TokenKind.ASCEND and self._last_meaningful_move(original_moves) in (TokenKind.DESCEND, TokenKind.SIBLING):
            self.current = parent
        else:
            self.current = node

    def _resolve_parent_for_next_node(self, target_name: str, quoted: bool) -> Node:
        if not self.moves:
            return self.root

        parent = self.current
        for move in self.moves:
            if move.kind == TokenKind.ASCEND:
                parent = self._ascend(parent, move.depth)
            elif move.kind == TokenKind.DESCEND:
                parent = self._descend(parent, move.depth, target_name=target_name, target_quoted=quoted)
            elif move.kind == TokenKind.SIBLING:
                parent = parent.parent or self.root

        return parent

    @staticmethod
    def _last_meaningful_move(moves: List[Move]) -> Optional[TokenKind]:
        if not moves:
            return None
        return moves[-1].kind

    @staticmethod
    def _should_reenter(moves: List[Move], quoted: bool) -> bool:
        if quoted:
            return False
        return any(move.kind == TokenKind.ASCEND for move in moves)

    def _add_or_reenter(self, parent: Node, name: str, quoted: bool, prefer_existing: bool) -> Node:
        key = clean_name(name)

        if prefer_existing and not quoted and key in self.index:
            return self.index[key]

        child = parent.add_child(key, quoted=quoted)

        if not quoted and key not in self.index:
            self.index[key] = child

        return child

    def _ascend(self, start: Node, depth: int) -> Node:
        node = start
        for _ in range(depth):
            if node.parent is None:
                node = self._wrap_top_visible_tree_with_unknown()
            elif node.parent == self.root:
                node = self._wrap_top_node_with_unknown(node)
            else:
                node = node.parent
        return node

    def _descend(self, start: Node, depth: int, target_name: str, target_quoted: bool) -> Node:
        parent = start

        # ':' means direct child, so there are zero intermediary steps.
        # ':::' means two intermediary steps, then the target node is placed.
        intermediary_steps = max(0, depth - 1)

        for steps_left in range(intermediary_steps, 0, -1):
            parent = self._choose_or_create_intermediary(parent, target_name, target_quoted, steps_left)

        return parent

    def _choose_or_create_intermediary(self, parent: Node, target_name: str, target_quoted: bool, steps_left: int) -> Node:
        # Use a known indexed path only if the target already exists and there is exactly one child path to it.
        # Do NOT treat "one existing child" as enough proof. That hides the unknown placeholders RTS wants to show.
        if not target_quoted:
            target = self.index.get(clean_name(target_name))
            if target is not None:
                candidates = [child for child in parent.children if self._is_ancestor(child, target)]
                if len(candidates) == 1:
                    return candidates[0]

        # If no safe inference exists, make the missing level visible.
        return parent.add_child("unknown")

    @staticmethod
    def _is_ancestor(possible_ancestor: Node, node: Node) -> bool:
        cur = node
        while cur.parent is not None:
            if cur is possible_ancestor:
                return True
            cur = cur.parent
        return cur is possible_ancestor

    def _wrap_top_node_with_unknown(self, top_node: Node) -> Node:
        if top_node.parent != self.root:
            raise RuntimeError("can only wrap top-level visible nodes")

        self.root.detach_child(top_node)
        unknown = Node("unknown", parent=self.root)
        unknown.add_existing_child(top_node)
        self.root.children.append(unknown)
        return unknown

    def _wrap_top_visible_tree_with_unknown(self) -> Node:
        if not self.root.children:
            unknown = Node("unknown", parent=self.root)
            self.root.children.append(unknown)
            return unknown

        top = self.root.children[0]
        return self._wrap_top_node_with_unknown(top)


def render(root: Node) -> str:
    lines: List[str] = []
    visible_roots = root.children

    for r_index, child in enumerate(visible_roots):
        _render_node(child, lines, prefix="", is_last=(r_index == len(visible_roots) - 1), is_root=True)
        if r_index != len(visible_roots) - 1:
            lines.append("")

    return "\n".join(lines)


def _render_node(node: Node, lines: List[str], prefix: str, is_last: bool, is_root: bool) -> None:
    label = f'"{node.name}"' if node.quoted else node.name

    if is_root:
        lines.append(label)
    else:
        connector = "└── " if is_last else "├── "
        lines.append(prefix + connector + label)

    child_prefix = "" if is_root else prefix + ("    " if is_last else "│   ")
    for i, child in enumerate(node.children):
        _render_node(child, lines, child_prefix, i == len(node.children) - 1, False)


def parse_and_render(expr: str) -> str:
    parser = Parser()
    root = parser.parse(expr)
    return render(root)


def run_tests() -> int:
    cases: List[Tuple[str, str]] = [
        (
            "mammalia:primates,carnivora|||plantae",
            """unknown
└── unknown
    └── unknown
        ├── mammalia
        │   ├── primates
        │   └── carnivora
        └── plantae""",
        ),
        (
            "mammalia:primates,carnivora|||::plantae",
            """unknown
└── unknown
    └── unknown
        ├── mammalia
        │   ├── primates
        │   └── carnivora
        └── unknown
            └── plantae""",
        ),
        (
            "life:animalia:chordata:mammalia:primates,carnivora|||fungi:ascomycota|plantae:angiosperms:rosids,asterids|||animalia:::cetacea||arthropoda:insecta|||plantae:bryophytes",
            """life
├── animalia
│   ├── chordata
│   │   └── mammalia
│   │       ├── primates
│   │       ├── carnivora
│   │       └── cetacea
│   └── arthropoda
│       └── insecta
├── fungi
│   └── ascomycota
└── plantae
    ├── angiosperms
    │   ├── rosids
    │   └── asterids
    └── bryophytes""",
        ),
        (
            'mammalia:"primates, advanced","carnivora: apex predators"',
            """mammalia
├── "primates, advanced"
└── "carnivora: apex predators""",
        ),
        (
            "life:animalia:chordata:mammalia:carnivora|||:::cetacea",
            """life
└── animalia
    └── chordata
        └── mammalia
            ├── carnivora
            └── cetacea""",
        ),
    ]

    failed = 0
    for expr, expected in cases:
        actual = parse_and_render(expr)
        if actual != expected:
            failed += 1
            print("FAIL:", expr)
            print("EXPECTED:")
            print(expected)
            print("ACTUAL:")
            print(actual)
            print("-" * 60)

    if failed == 0:
        print(f"All {len(cases)} tests passed.")
        return 0

    print(f"{failed} test(s) failed.")
    return 1


def read_expression(args: argparse.Namespace) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8").strip()

    if args.stdin:
        return sys.stdin.read().strip()

    if args.expression:
        return " ".join(args.expression).strip()

    raise ValueError("no RTS expression provided")


def watch_mode() -> int:
    print("bra-vis watch mode")
    print("Type RTS expressions. Empty line exits.")
    print()

    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break

        if not line:
            break

        try:
            print(parse_and_render(line))
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bravis",
        description="Branch Visibility for xmeta Relative Taxonomy Shorthand (RTS).",
    )
    ap.add_argument("expression", nargs="*", help="RTS expression to render")
    ap.add_argument("-f", "--file", help="read RTS expression from file")
    ap.add_argument("-", dest="stdin", action="store_true", help="read RTS expression from stdin")
    ap.add_argument("--watch", action="store_true", help="interactive watch mode")
    ap.add_argument("--test", action="store_true", help="run parser tests")

    args = ap.parse_args(argv)

    try:
        if args.test:
            return run_tests()

        if args.watch:
            return watch_mode()

        expr = read_expression(args)
        print(parse_and_render(expr))
        return 0
    except Exception as exc:
        print(f"bra-vis error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
