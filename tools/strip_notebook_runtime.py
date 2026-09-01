from __future__ import annotations

import ast
import builtins
import shutil
from pathlib import Path


PROJECT_ROOT = Path(
    r"C:\Users\shubh\Desktop\Projects\Copilot"
)

PIPELINE_PATH = (
    PROJECT_ROOT
    / "src"
    / "copilot"
    / "pipeline.py"
)

BACKUP_PATH = (
    PROJECT_ROOT
    / "src"
    / "copilot"
    / "pipeline_before_runtime_strip.py"
)

BUILTINS = set(dir(builtins))


# ============================================================
# HELPERS
# ============================================================

def root_name(node):

    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        return root_name(node.value)

    if isinstance(node, ast.Subscript):
        return root_name(node.value)

    return None


def assigned_names(node):

    names = set()

    for child in ast.walk(node):

        if (
            isinstance(child, ast.Name)
            and
            isinstance(child.ctx, ast.Store)
        ):
            names.add(child.id)

        elif (
            isinstance(child, ast.Subscript)
            and
            isinstance(child.ctx, ast.Store)
        ):

            root = root_name(child)

            if root:
                names.add(root)

        elif (
            isinstance(child, ast.Attribute)
            and
            isinstance(child.ctx, ast.Store)
        ):

            root = root_name(child)

            if root:
                names.add(root)

    return names


def function_global_reads(node):

    args = set()

    for arg in (
        list(node.args.posonlyargs)
        + list(node.args.args)
        + list(node.args.kwonlyargs)
    ):
        args.add(arg.arg)

    if node.args.vararg:
        args.add(node.args.vararg.arg)

    if node.args.kwarg:
        args.add(node.args.kwarg.arg)

    local_names = set(args)
    declared_globals = set()

    for child in ast.walk(node):

        if isinstance(child, ast.Global):

            declared_globals.update(
                child.names
            )

        elif (
            isinstance(child, ast.Name)
            and
            isinstance(child.ctx, ast.Store)
        ):

            local_names.add(
                child.id
            )

    local_names -= declared_globals

    loads = {
        child.id
        for child in ast.walk(node)
        if (
            isinstance(child, ast.Name)
            and
            isinstance(child.ctx, ast.Load)
        )
    }

    return {
        name
        for name in loads
        if (
            name not in local_names
            and
            name not in BUILTINS
        )
    }


def direct_called_names(node):

    names = set()

    for child in ast.walk(node):

        if not isinstance(
            child,
            ast.Call,
        ):
            continue

        if isinstance(
            child.func,
            ast.Name,
        ):

            names.add(
                child.func.id
            )

    return names


def contains_print_or_display(node):

    for child in ast.walk(node):

        if (
            isinstance(
                child,
                ast.Call,
            )
            and
            isinstance(
                child.func,
                ast.Name,
            )
            and
            child.func.id
            in {
                "print",
                "display",
            }
        ):

            return True

    return False


# ============================================================
# LOAD CURRENT SANITIZED PIPELINE
# ============================================================

if not PIPELINE_PATH.exists():

    raise FileNotFoundError(
        PIPELINE_PATH
    )


shutil.copy2(
    PIPELINE_PATH,
    BACKUP_PATH,
)


source = PIPELINE_PATH.read_text(
    encoding="utf-8-sig"
)

tree = ast.parse(
    source
)

statements = list(
    tree.body
)


# ============================================================
# LOCAL FUNCTION NAMES
# ============================================================

local_functions = {
    node.name
    for node in statements
    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    )
}


# ============================================================
# GLOBALS REQUIRED AT RUNTIME
# ============================================================

required_globals = set()


for node in statements:

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):

        required_globals.update(
            function_global_reads(
                node
            )
        )


print(
    "Runtime globals detected:",
    len(required_globals),
)


# ============================================================
# CLASSIFY TOP-LEVEL STATEMENTS
# ============================================================

kept = []
removed = []


for node in statements:

    # Always retain imports, functions and classes.
    if isinstance(
        node,
        (
            ast.Import,
            ast.ImportFrom,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        ),
    ):

        kept.append(node)
        continue


    # Retain module docstring.
    if (
        isinstance(node, ast.Expr)
        and
        isinstance(
            node.value,
            ast.Constant,
        )
        and
        isinstance(
            node.value.value,
            str,
        )
    ):

        kept.append(node)
        continue


    assigned = assigned_names(
        node
    )

    called = direct_called_names(
        node
    )


    # --------------------------------------------------------
    # Required global initialization
    # --------------------------------------------------------

    if (
        assigned
        &
        required_globals
    ):

        kept.append(node)
        continue


    # --------------------------------------------------------
    # Constants / configuration
    # --------------------------------------------------------

    if isinstance(
        node,
        (
            ast.Assign,
            ast.AnnAssign,
        ),
    ):

        targets = (
            node.targets
            if isinstance(
                node,
                ast.Assign,
            )
            else
            [node.target]
        )

        simple_targets = [
            target.id
            for target in targets
            if isinstance(
                target,
                ast.Name,
            )
        ]

        # Retain uppercase configuration/constants.
        if (
            simple_targets
            and
            all(
                name.upper() == name
                for name
                in simple_targets
            )
        ):

            kept.append(node)
            continue


    # --------------------------------------------------------
    # Remove notebook execution
    # --------------------------------------------------------

    if isinstance(
        node,
        ast.Assert,
    ):

        removed.append(node)
        continue


    if contains_print_or_display(
        node
    ):

        removed.append(node)
        continue


    # A direct top-level call to one of our own functions
    # is notebook execution, not module initialization,
    # unless it populated a required global above.
    if (
        called
        &
        local_functions
    ):

        removed.append(node)
        continue


    # --------------------------------------------------------
    # Keep harmless initialization statements
    # --------------------------------------------------------

    kept.append(node)


# ============================================================
# WRITE
# ============================================================

new_tree = ast.Module(
    body=kept,
    type_ignores=[],
)

ast.fix_missing_locations(
    new_tree
)


new_source = ast.unparse(
    new_tree
)


new_source = new_source.replace(
    "PROJECT_ROOT = Path('..').resolve()",
    (
        "PROJECT_ROOT = "
        "Path(__file__).resolve().parents[2]"
    ),
)


header = '''"""
Production module generated from the frozen V3 pipeline.

Notebook demonstrations and evaluation executions have been
removed. Model, retrieval, routing and synthesis behaviour
remain frozen after final holdout evaluation.
"""

'''


new_source = (
    header
    +
    new_source
    +
    "\n"
)


compile(
    new_source,
    str(PIPELINE_PATH),
    "exec",
)


PIPELINE_PATH.write_text(
    new_source,
    encoding="utf-8",
)


print("=" * 80)
print("NOTEBOOK RUNTIME STRIPPED")
print("=" * 80)

print(
    "Statements before:",
    len(statements),
)

print(
    "Statements retained:",
    len(kept),
)

print(
    "Statements removed:",
    len(removed),
)

print(
    "Backup:",
    BACKUP_PATH,
)

print(
    "Output:",
    PIPELINE_PATH,
)
