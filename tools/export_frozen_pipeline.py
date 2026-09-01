from __future__ import annotations

import ast
import builtins
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(
    r"C:\Users\shubh\Desktop\Projects\Copilot"
)

NOTEBOOK_DIR = PROJECT_ROOT / "notebooks"

OUTPUT_PATH = (
    PROJECT_ROOT
    / "src"
    / "copilot"
    / "pipeline.py"
)

TARGET_SYMBOL = "run_stage5_pipeline_v2"

PIPELINE_MARKERS = (
    "run_stage5_pipeline_v2",
    "execute_query_plan",
    "search_trial_evidence",
    "AnswerContractError",
    "emit_query_plan",
    "emit_grounded_answer",
    "ACTIVE_RATIO_PATTERNS",
    "enforce_company_program_consistency",
    "normalize_plan_for_question",
)

BUILTINS = set(dir(builtins))


@dataclass
class StatementInfo:
    index: int
    notebook: Path
    cell_index: int
    node: ast.stmt
    overwrites: set[str]
    mutates: set[str]
    reads: set[str]


def clean_cell_source(source: str) -> str:

    cleaned = []

    for line in source.splitlines():

        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        if stripped.startswith("%%"):
            continue

        if stripped.startswith("%"):
            cleaned.append(indent + "pass")
            continue

        if stripped.startswith("!"):
            cleaned.append(indent + "pass")
            continue

        if stripped.startswith("?"):
            cleaned.append(indent + "pass")
            continue

        if "get_ipython()" in stripped:
            cleaned.append(indent + "pass")
            continue

        cleaned.append(line)

    return "\n".join(cleaned)


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


class TopLevelWriteVisitor(ast.NodeVisitor):

    def __init__(self):
        self.overwrites = set()
        self.mutates = set()

    def visit_FunctionDef(self, node):
        return

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_ClassDef(self, node):
        return

    def visit_Name(self, node):

        if isinstance(node.ctx, ast.Store):
            self.overwrites.add(node.id)

    def visit_Subscript(self, node):

        if isinstance(node.ctx, ast.Store):

            root = root_name(node)

            if root:
                self.mutates.add(root)

        self.generic_visit(node)

    def visit_Attribute(self, node):

        if isinstance(node.ctx, ast.Store):

            root = root_name(node)

            if root:
                self.mutates.add(root)

        self.generic_visit(node)

    def visit_Call(self, node):

        if isinstance(node.func, ast.Attribute):

            root = root_name(node.func.value)

            if root:
                self.mutates.add(root)

        self.generic_visit(node)


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

    local_stores = set(args)
    global_declared = set()

    for child in ast.walk(node):

        if isinstance(child, ast.Global):
            global_declared.update(child.names)

        elif (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Store)
        ):
            local_stores.add(child.id)

    loads = {
        child.id
        for child in ast.walk(node)
        if (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
        )
    }

    local_stores -= global_declared

    return {
        name
        for name in loads
        if name not in local_stores
        and name not in BUILTINS
    }


def statement_reads(node):

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):
        return function_global_reads(node)

    loads = {
        child.id
        for child in ast.walk(node)
        if (
            isinstance(child, ast.Name)
            and isinstance(child.ctx, ast.Load)
        )
    }

    return {
        name
        for name in loads
        if name not in BUILTINS
    }


def analyze_statement(
    index,
    notebook,
    cell_index,
    node,
):

    overwrites = set()
    mutates = set()

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
        ),
    ):

        overwrites.add(node.name)

    elif isinstance(node, ast.Import):

        for alias in node.names:

            overwrites.add(
                alias.asname
                or alias.name.split(".")[0]
            )

    elif isinstance(node, ast.ImportFrom):

        for alias in node.names:

            if alias.name == "*":
                continue

            overwrites.add(
                alias.asname
                or alias.name
            )

    elif isinstance(node, ast.Assign):

        for target in node.targets:

            if isinstance(target, ast.Name):

                overwrites.add(
                    target.id
                )

            else:

                root = root_name(
                    target
                )

                if root:
                    mutates.add(root)

    elif isinstance(
        node,
        ast.AnnAssign,
    ):

        target = node.target

        if isinstance(target, ast.Name):

            overwrites.add(
                target.id
            )

        else:

            root = root_name(
                target
            )

            if root:
                mutates.add(root)

    elif isinstance(
        node,
        ast.AugAssign,
    ):

        root = root_name(
            node.target
        )

        if root:
            mutates.add(root)

    else:

        visitor = (
            TopLevelWriteVisitor()
        )

        visitor.visit(node)

        overwrites |= (
            visitor.overwrites
        )

        mutates |= (
            visitor.mutates
        )

    return StatementInfo(
        index=index,
        notebook=notebook,
        cell_index=cell_index,
        node=node,
        overwrites=overwrites,
        mutates=mutates,
        reads=statement_reads(node),
    )


if not NOTEBOOK_DIR.exists():

    raise FileNotFoundError(
        f"Notebook directory not found: "
        f"{NOTEBOOK_DIR}"
    )


all_notebooks = sorted(
    NOTEBOOK_DIR.rglob(
        "*.ipynb"
    )
)

relevant_notebooks = []


for notebook in all_notebooks:

    try:

        payload = json.loads(
            notebook.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        continue

    text = "\n".join(
        "".join(
            cell.get(
                "source",
                [],
            )
        )
        for cell in payload.get(
            "cells",
            [],
        )
    )

    if any(
        marker in text
        for marker in PIPELINE_MARKERS
    ):

        relevant_notebooks.append(
            notebook
        )


if not relevant_notebooks:

    raise RuntimeError(
        "No notebook containing the frozen "
        "Stage 5/6 pipeline was found."
    )


print("\nRelevant notebooks:")

for notebook in relevant_notebooks:

    print(
        " -",
        notebook.relative_to(
            PROJECT_ROOT
        ),
    )


statements = []

statement_index = 0


for notebook in relevant_notebooks:

    payload = json.loads(
        notebook.read_text(
            encoding="utf-8"
        )
    )

    for cell_index, cell in enumerate(
        payload.get(
            "cells",
            [],
        )
    ):

        if (
            cell.get(
                "cell_type"
            )
            !=
            "code"
        ):
            continue

        source = "".join(
            cell.get(
                "source",
                [],
            )
        )

        source = clean_cell_source(
            source
        )

        if not source.strip():
            continue

        try:

            tree = ast.parse(
                source
            )

        except SyntaxError:

            if any(
                marker in source
                for marker in PIPELINE_MARKERS
            ):

                print(
                    "\nWARNING: "
                    "pipeline-related cell "
                    "could not be parsed:"
                )

                print(
                    notebook.name,
                    "cell",
                    cell_index,
                )

            continue

        for node in tree.body:

            info = analyze_statement(
                index=statement_index,
                notebook=notebook,
                cell_index=cell_index,
                node=node,
            )

            statements.append(
                info
            )

            statement_index += 1


writers = defaultdict(list)
mutators = defaultdict(list)


for statement in statements:

    for name in (
        statement.overwrites
    ):

        writers[name].append(
            statement
        )

    for name in (
        statement.mutates
    ):

        mutators[name].append(
            statement
        )


if TARGET_SYMBOL not in writers:

    raise RuntimeError(
        f"{TARGET_SYMBOL!r} was not found "
        "in the relevant notebooks."
    )


included_indices = set()
processed_requests = set()


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
            item
            for item in candidates
            if item.index < before
        ]

    if not candidates:
        return None

    return candidates[-1]


def request_symbol(
    name,
    before=None,
):

    if name in BUILTINS:
        return

    key = (
        name,
        before,
    )

    if key in processed_requests:
        return

    processed_requests.add(
        key
    )

    writer = latest_writer(
        name,
        before=before,
    )

    if writer is None:
        return

    include_statement(
        writer
    )

    if before is None:

        for mutation in (
            mutators.get(
                name,
                [],
            )
        ):

            if (
                mutation.index
                >
                writer.index
            ):

                include_statement(
                    mutation
                )


def include_statement(
    statement,
):

    if (
        statement.index
        in included_indices
    ):
        return

    included_indices.add(
        statement.index
    )

    node = statement.node

    if isinstance(
        node,
        (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):

        for dependency in (
            statement.reads
        ):

            request_symbol(
                dependency,
                before=None,
            )

        return

    for dependency in (
        statement.reads
    ):

        request_symbol(
            dependency,
            before=statement.index,
        )


request_symbol(
    TARGET_SYMBOL,
    before=None,
)


changed = True

while changed:

    before_count = len(
        included_indices
    )

    current_names = set()

    for idx in (
        included_indices
    ):

        current_names |= (
            statements[
                idx
            ].overwrites
        )

        current_names |= (
            statements[
                idx
            ].mutates
        )

    for name in current_names:

        writer = latest_writer(
            name
        )

        if (
            writer is None
            or writer.index
            not in included_indices
        ):
            continue

        for mutation in (
            mutators.get(
                name,
                [],
            )
        ):

            if (
                mutation.index
                >
                writer.index
            ):

                include_statement(
                    mutation
                )

    changed = (
        len(included_indices)
        >
        before_count
    )


selected = [
    statements[idx]
    for idx in sorted(
        included_indices
    )
]


future_imports = []
normal_nodes = []


for statement in selected:

    node = statement.node

    if (
        isinstance(
            node,
            ast.ImportFrom,
        )
        and
        node.module
        ==
        "__future__"
    ):

        future_imports.append(
            node
        )

    else:

        normal_nodes.append(
            node
        )


module = ast.Module(
    body=[
        *future_imports,
        *normal_nodes,
    ],
    type_ignores=[],
)

ast.fix_missing_locations(
    module
)


generated_source = (
    ast.unparse(
        module
    )
)


header = '''"""
AUTO-GENERATED FROM THE FROZEN STAGE 5/6 NOTEBOOKS.

Do not modify modelling, routing, retrieval, semantic,
or synthesis behaviour in this file.

Production changes after the final holdout are limited
to packaging, serving, configuration and infrastructure.
"""

'''


generated_source = (
    header
    +
    generated_source
    +
    "\n"
)


compile(
    generated_source,
    str(
        OUTPUT_PATH
    ),
    "exec",
)


OUTPUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True,
)


OUTPUT_PATH.write_text(
    generated_source,
    encoding="utf-8",
)


print("\n" + "=" * 80)
print("FROZEN PIPELINE EXPORTED")
print("=" * 80)

print(
    "\nOutput:",
    OUTPUT_PATH,
)

print(
    "\nSelected statements:",
    len(selected),
)

print(
    "\nNext:"
)

print(
    'python -c "from src.copilot.pipeline '
    'import run_stage5_pipeline_v2; '
    'print(\'PIPELINE IMPORT OK\')"'
)
