from __future__ import annotations

import ast
import builtins
import shutil
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(
    r"C:\Users\shubh\Desktop\Projects\Copilot"
)

SOURCE_PATH = (
    PROJECT_ROOT
    / "src"
    / "copilot"
    / "pipeline_before_sanitize.py"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "src"
    / "copilot"
    / "pipeline.py"
)

FINAL_BACKUP = (
    PROJECT_ROOT
    / "src"
    / "copilot"
    / "pipeline_failed_runtime_version.py"
)

TARGET = "run_stage5_pipeline_v2"

BUILTINS = set(dir(builtins))


# ============================================================
# BASIC AST HELPERS
# ============================================================

def root_name(node):

    if node is None:
        return None

    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        return root_name(node.value)

    if isinstance(node, ast.Subscript):
        return root_name(node.value)

    return None


def assignment_targets(node):

    names = set()

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        ),
    ):
        names.add(node.name)

    elif isinstance(node, ast.Import):

        for alias in node.names:

            names.add(
                alias.asname
                or
                alias.name.split(".")[0]
            )

    elif isinstance(node, ast.ImportFrom):

        for alias in node.names:

            if alias.name != "*":

                names.add(
                    alias.asname
                    or
                    alias.name
                )

    elif isinstance(node, ast.Assign):

        for target in node.targets:

            if isinstance(target, ast.Name):

                names.add(
                    target.id
                )

    elif isinstance(node, ast.AnnAssign):

        if isinstance(
            node.target,
            ast.Name,
        ):

            names.add(
                node.target.id
            )

    return names


# ============================================================
# GLOBAL MUTATION DETECTION
# ============================================================

class MutationVisitor(ast.NodeVisitor):

    MUTATING_METHODS = {
        "update",
        "append",
        "extend",
        "add",
        "remove",
        "discard",
        "clear",
        "setdefault",
        "sort",
        "pop",
    }

    def __init__(self):

        self.names = set()


    def visit_FunctionDef(
        self,
        node,
    ):
        return


    def visit_AsyncFunctionDef(
        self,
        node,
    ):
        return


    def visit_ClassDef(
        self,
        node,
    ):
        return


    def visit_Subscript(
        self,
        node,
    ):

        if isinstance(
            node.ctx,
            ast.Store,
        ):

            root = root_name(
                node
            )

            if root:
                self.names.add(root)

        self.generic_visit(node)


    def visit_Attribute(
        self,
        node,
    ):

        if isinstance(
            node.ctx,
            ast.Store,
        ):

            root = root_name(
                node
            )

            if root:
                self.names.add(root)

        self.generic_visit(node)


    def visit_Call(
        self,
        node,
    ):

        if (
            isinstance(
                node.func,
                ast.Attribute,
            )
            and
            node.func.attr
            in self.MUTATING_METHODS
        ):

            root = root_name(
                node.func.value
            )

            if root:
                self.names.add(root)

        self.generic_visit(node)


def mutation_targets(node):

    visitor = MutationVisitor()

    visitor.visit(node)

    return visitor.names


# ============================================================
# GLOBAL READ DETECTION
# ============================================================

def function_global_reads(node):

    params = set()

    for arg in (
        list(node.args.posonlyargs)
        +
        list(node.args.args)
        +
        list(node.args.kwonlyargs)
    ):

        params.add(
            arg.arg
        )

    if node.args.vararg:
        params.add(
            node.args.vararg.arg
        )

    if node.args.kwarg:
        params.add(
            node.args.kwarg.arg
        )


    local_names = set(
        params
    )

    explicitly_global = set()


    for child in ast.walk(node):

        if isinstance(
            child,
            ast.Global,
        ):

            explicitly_global.update(
                child.names
            )

        elif (
            isinstance(
                child,
                ast.Name,
            )
            and
            isinstance(
                child.ctx,
                ast.Store,
            )
        ):

            local_names.add(
                child.id
            )


    local_names -= (
        explicitly_global
    )


    loads = {
        child.id
        for child in ast.walk(node)
        if (
            isinstance(
                child,
                ast.Name,
            )
            and
            isinstance(
                child.ctx,
                ast.Load,
            )
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


def ordinary_reads(node):

    loads = {
        child.id
        for child in ast.walk(node)
        if (
            isinstance(
                child,
                ast.Name,
            )
            and
            isinstance(
                child.ctx,
                ast.Load,
            )
        )
    }

    stores = {
        child.id
        for child in ast.walk(node)
        if (
            isinstance(
                child,
                ast.Name,
            )
            and
            isinstance(
                child.ctx,
                ast.Store,
            )
        )
    }

    return {
        name
        for name in loads
        if (
            name not in stores
            and
            name not in BUILTINS
        )
    }


def reads(node):

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):

        return function_global_reads(
            node
        )

    return ordinary_reads(
        node
    )


# ============================================================
# LOAD ORIGINAL EXPORTED MODULE
# ============================================================

if not SOURCE_PATH.exists():

    raise FileNotFoundError(
        f"Missing source backup: {SOURCE_PATH}"
    )


if OUTPUT_PATH.exists():

    shutil.copy2(
        OUTPUT_PATH,
        FINAL_BACKUP,
    )


source = SOURCE_PATH.read_text(
    encoding="utf-8-sig"
)

tree = ast.parse(source)

statements = list(
    tree.body
)


# ============================================================
# INDEX DEFINITIONS + MUTATIONS
# ============================================================

writers = defaultdict(list)
mutators = defaultdict(list)


for index, node in enumerate(
    statements
):

    for name in assignment_targets(
        node
    ):

        writers[name].append(
            index
        )

    for name in mutation_targets(
        node
    ):

        mutators[name].append(
            index
        )


if TARGET not in writers:

    raise RuntimeError(
        f"{TARGET} was not found."
    )


# ============================================================
# DEPENDENCY CLOSURE
# ============================================================

selected = set()
processed = set()


def latest_writer(
    name,
    before=None,
):

    candidates = writers.get(
        name,
        [],
    )

    if before is not None:

        candidates = [
            index
            for index in candidates
            if index < before
        ]

    if not candidates:
        return None

    return candidates[-1]


def request_symbol(
    name,
    before=None,
):

    key = (
        name,
        before,
    )

    if key in processed:
        return

    processed.add(key)


    writer = latest_writer(
        name,
        before,
    )

    if writer is None:
        return


    include_statement(
        writer
    )


    # Preserve mutations that form the state of the
    # selected global before it is used.
    upper_bound = (
        len(statements)
        if before is None
        else before
    )


    for mutation_index in (
        mutators.get(
            name,
            [],
        )
    ):

        if (
            writer
            <
            mutation_index
            <
            upper_bound
        ):

            include_statement(
                mutation_index
            )


def include_statement(
    index,
):

    if index in selected:
        return

    selected.add(index)

    node = statements[
        index
    ]


    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):

        # Python functions resolve module globals
        # when they execute, so use final bindings.
        for dependency in reads(
            node
        ):

            request_symbol(
                dependency,
                before=None,
            )

    else:

        # Top-level expressions execute in source
        # order. Use the definition existing at
        # that point in the notebook/module.
        for dependency in reads(
            node
        ):

            request_symbol(
                dependency,
                before=index,
            )


request_symbol(
    TARGET,
    before=None,
)


# ============================================================
# BUILD MODULE IN ORIGINAL ORDER
# ============================================================

selected_nodes = [
    statements[index]
    for index in sorted(
        selected
    )
]


# Hard rule:
# no unrelated notebook asserts or print-only expressions.
filtered_nodes = []


for node in selected_nodes:

    if isinstance(
        node,
        ast.Assert,
    ):
        continue

    if isinstance(
        node,
        ast.Expr,
    ):

        value = node.value

        if (
            isinstance(
                value,
                ast.Call,
            )
            and
            isinstance(
                value.func,
                ast.Name,
            )
            and
            value.func.id
            in {
                "print",
                "display",
            }
        ):
            continue

    filtered_nodes.append(
        node
    )


new_tree = ast.Module(
    body=filtered_nodes,
    type_ignores=[],
)

ast.fix_missing_locations(
    new_tree
)


new_source = ast.unparse(
    new_tree
)


# ============================================================
# PRODUCTION-SAFE PROJECT ROOT
# ============================================================

new_source = new_source.replace(
    "PROJECT_ROOT = Path('..').resolve()",
    (
        "PROJECT_ROOT = "
        "Path(__file__).resolve().parents[2]"
    ),
)


header = '''"""
Frozen V3 production pipeline.

Generated from the evaluated notebook implementation using
the dependency closure of run_stage5_pipeline_v2.

Notebook examples, smoke tests and evaluation executions are
excluded. Model, retrieval, routing and synthesis logic remains
frozen after the final holdout.
"""

'''


new_source = (
    header
    +
    new_source
    +
    "\n"
)


# ============================================================
# STATIC SAFETY CHECKS
# ============================================================

for forbidden in (
    "survodutide_test =",
    "survodutide_execution =",
    "result = execute_query_plan(plan)",
):

    if forbidden in new_source:

        raise RuntimeError(
            "Notebook runtime statement "
            f"survived dependency slicing: "
            f"{forbidden}"
        )


compile(
    new_source,
    str(OUTPUT_PATH),
    "exec",
)


OUTPUT_PATH.write_text(
    new_source,
    encoding="utf-8",
)


print("=" * 80)
print("PRODUCTION PIPELINE BUILT")
print("=" * 80)

print(
    "Original statements:",
    len(statements),
)

print(
    "Selected dependency statements:",
    len(selected_nodes),
)

print(
    "Final production statements:",
    len(filtered_nodes),
)

print(
    "Output:",
    OUTPUT_PATH,
)

print(
    "Previous failed version:",
    FINAL_BACKUP,
)
