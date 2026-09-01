from __future__ import annotations

import ast
import builtins
import shutil
from collections import defaultdict
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
    / "pipeline_before_sanitize.py"
)

TARGET = "run_stage5_pipeline_v2"

BUILTINS = set(
    dir(builtins)
)


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


def defined_names(node):

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

    elif isinstance(
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

        for target in targets:

            if isinstance(
                target,
                ast.Name,
            ):
                names.add(
                    target.id
                )

    elif isinstance(
        node,
        (
            ast.For,
            ast.While,
            ast.If,
            ast.Try,
        ),
    ):

        for child in ast.walk(node):

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
            ):
                names.add(
                    child.id
                )

    return names


class MutationVisitor(ast.NodeVisitor):

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

            name = root_name(node)

            if name:
                self.names.add(
                    name
                )

        self.generic_visit(node)

    def visit_Attribute(
        self,
        node,
    ):

        if isinstance(
            node.ctx,
            ast.Store,
        ):

            name = root_name(node)

            if name:
                self.names.add(
                    name
                )

        self.generic_visit(node)

    def visit_Call(
        self,
        node,
    ):

        if isinstance(
            node.func,
            ast.Attribute,
        ):

            method = (
                node.func.attr
            )

            if method in {
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
            }:

                name = root_name(
                    node.func.value
                )

                if name:
                    self.names.add(
                        name
                    )

        self.generic_visit(node)


def mutated_names(node):

    visitor = MutationVisitor()

    visitor.visit(node)

    return visitor.names


def function_global_reads(
    node,
):

    args = set()

    for arg in (
        list(
            node.args.posonlyargs
        )
        +
        list(
            node.args.args
        )
        +
        list(
            node.args.kwonlyargs
        )
    ):
        args.add(
            arg.arg
        )

    if node.args.vararg:
        args.add(
            node.args.vararg.arg
        )

    if node.args.kwarg:
        args.add(
            node.args.kwarg.arg
        )

    local_names = set(
        args
    )

    global_names = set()

    for child in ast.walk(node):

        if isinstance(
            child,
            ast.Global,
        ):

            global_names.update(
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
        global_names
    )

    reads = {
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
        for name in reads
        if (
            name not in local_names
            and
            name not in BUILTINS
        )
    }


def read_names(node):

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

    reads = {
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
        for name in reads
        if name not in BUILTINS
    }


# ============================================================
# LOAD MODULE
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


writers = defaultdict(
    list
)

mutators = defaultdict(
    list
)


for index, node in enumerate(
    statements
):

    for name in defined_names(
        node
    ):

        writers[name].append(
            index
        )

    for name in mutated_names(
        node
    ):

        mutators[name].append(
            index
        )


if TARGET not in writers:

    raise RuntimeError(
        f"{TARGET} not found"
    )


# ============================================================
# DEPENDENCY SLICE
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
            idx
            for idx in candidates
            if idx < before
        ]

    if not candidates:
        return None

    return candidates[-1]


def include_symbol(
    name,
    before=None,
):

    key = (
        name,
        before,
    )

    if key in processed:
        return

    processed.add(
        key
    )

    writer = latest_writer(
        name,
        before,
    )

    if writer is None:
        return

    include_statement(
        writer
    )


def include_statement(
    index,
):

    if index in selected:
        return

    selected.add(
        index
    )

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

        # Functions resolve globals when called,
        # so use the final runtime definition.
        for name in read_names(
            node
        ):

            include_symbol(
                name,
                before=None,
            )

    else:

        # Top-level initialization executes in
        # source order.
        for name in read_names(
            node
        ):

            include_symbol(
                name,
                before=index,
            )


include_symbol(
    TARGET,
    before=None,
)


# ============================================================
# PRESERVE REQUIRED MUTATIONS TO SELECTED GLOBALS
# ============================================================

changed = True

while changed:

    old_count = len(
        selected
    )

    selected_globals = set()

    for index in selected:

        selected_globals.update(
            defined_names(
                statements[
                    index
                ]
            )
        )

    for name in list(
        selected_globals
    ):

        final_writer = (
            latest_writer(
                name
            )
        )

        if (
            final_writer is None
            or
            final_writer
            not in selected
        ):
            continue

        for mutation_index in (
            mutators.get(
                name,
                [],
            )
        ):

            if (
                mutation_index
                >
                final_writer
            ):

                include_statement(
                    mutation_index
                )

    changed = (
        len(selected)
        >
        old_count
    )


# ============================================================
# BUILD CLEAN MODULE
# ============================================================

clean_nodes = [
    statements[index]
    for index in sorted(
        selected
    )
]


clean_tree = ast.Module(
    body=clean_nodes,
    type_ignores=[],
)

ast.fix_missing_locations(
    clean_tree
)


clean_source = ast.unparse(
    clean_tree
)


# Production-safe project root.
clean_source = clean_source.replace(
    "PROJECT_ROOT = Path('..').resolve()",
    (
        "PROJECT_ROOT = "
        "Path(__file__).resolve().parents[2]"
    ),
)


header = '''"""
Production module generated from the frozen V3 notebook pipeline.

Model, retrieval, routing and synthesis logic remain frozen.
Notebook demonstrations and evaluation executions are excluded.
"""

'''


clean_source = (
    header
    +
    clean_source
    +
    "\n"
)


compile(
    clean_source,
    str(
        PIPELINE_PATH
    ),
    "exec",
)


PIPELINE_PATH.write_text(
    clean_source,
    encoding="utf-8",
)


print(
    "=" * 80
)

print(
    "PIPELINE SANITIZED"
)

print(
    "=" * 80
)

print(
    "Original statements:",
    len(statements),
)

print(
    "Production statements:",
    len(clean_nodes),
)

print(
    "Backup:",
    BACKUP_PATH,
)

print(
    "Output:",
    PIPELINE_PATH,
)
