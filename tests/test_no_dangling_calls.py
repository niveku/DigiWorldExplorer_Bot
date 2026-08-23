"""No call may name a function that does not exist.

Why this exists: deleting the six-mechanism suspicion stack left one
live call to `dash_pickup_log` inside main(). Every one of the 400 unit
tests passed - main() is the live ADB loop, so nothing executes it - and
the bot died on the user's machine with a NameError three frames in.
Import-time checks cannot see it either: Python resolves names when the
line runs.

So the check is static: walk each module's AST, collect every name that
can be bound in a scope (imports, defs, classes, assignments, function
parameters, loop and with targets, comprehension variables, except
aliases, walrus), and assert that every called name resolves to one of
them or to a builtin. Cheap, and it catches the whole class - a rename,
a deletion, a typo in a rarely-taken branch.
"""
import ast
import builtins
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULES = ["auto_digiworld.py", "auto_digiworld_batch2.py",
           "replay_harness.py", "world_model.py", "digiworld_bot.py"]


def _bound_names(node):
    """Names this scope binds, without descending into nested scopes."""
    names = set()
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = node.args
        for arg in (list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)
                    + [a.vararg, a.kwarg]):
            if arg is not None:
                names.add(arg.arg)
    stack = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)):
            names.add(child.name)
            continue                      # its body is another scope
        if isinstance(child, ast.Lambda):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            for alias in child.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            names.add(child.id)
        elif isinstance(child, ast.ExceptHandler) and child.name:
            names.add(child.name)
        elif isinstance(child, ast.Global) or isinstance(child, ast.Nonlocal):
            names.update(child.names)
        stack.extend(ast.iter_child_nodes(child))
    return names


def dangling_calls(source, filename="<module>"):
    """[(line, name)] for called names nothing in scope can provide."""
    tree = ast.parse(source, filename)
    problems = []

    def walk(node, visible):
        visible = visible | _bound_names(node)
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
        for child in ast.iter_child_nodes(node):
            _descend(child, visible)

    def _descend(node, visible):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Lambda)):
            walk(node, visible)
            return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in visible:
                problems.append((node.lineno, node.func.id))
        for child in ast.iter_child_nodes(node):
            _descend(child, visible)

    walk(tree, set(dir(builtins)))
    return problems


class NoDanglingCallsTests(unittest.TestCase):
    def test_every_module_calls_only_names_that_exist(self):
        found = {}
        for name in MODULES:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                bad = dangling_calls(fh.read(), name)
            if bad:
                found[name] = bad
        self.assertEqual(found, {})

    def test_the_checker_actually_catches_a_deleted_function(self):
        # The exact shape of the 2026-08-22 crash: the helper is gone,
        # the call inside a never-unit-tested branch is not.
        source = ("def main():\n"
                  "    if False:\n"
                  "        return dash_pickup_log([], (2, 1), 3)\n")
        self.assertEqual(dangling_calls(source), [(3, "dash_pickup_log")])

    def test_the_checker_accepts_parameters_and_locals(self):
        source = ("def retry(tap, capture):\n"
                  "    def inner():\n"
                  "        return tap()\n"
                  "    helper = inner\n"
                  "    return helper(), capture()\n")
        self.assertEqual(dangling_calls(source), [])


if __name__ == "__main__":
    unittest.main()
