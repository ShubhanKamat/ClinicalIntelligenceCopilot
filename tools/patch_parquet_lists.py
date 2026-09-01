from pathlib import Path
import re

path = Path(
    r"C:\Users\shubh\Desktop\Projects\Copilot\src\copilot\pipeline.py"
)

text = path.read_text(
    encoding="utf-8-sig"
)

# Ensure json is available before parse_list().
if "import json" not in text:
    text = text.replace(
        "from pathlib import Path",
        "from pathlib import Path\nimport json",
        1,
    )

# Add Stage 5 semantic list fields to list normalization.
old_list = """LIST_COLUMNS = ['phases', 'conditions', 'keywords', 'intervention_names', 'intervention_types', 'intervention_descriptions', 'primary_outcomes', 'secondary_outcomes', 'countries', 'states', 'cities', 'canonical_interventions', 'normalized_programs']"""

new_list = """LIST_COLUMNS = ['phases', 'conditions', 'keywords', 'intervention_names', 'intervention_types', 'intervention_descriptions', 'primary_outcomes', 'secondary_outcomes', 'countries', 'states', 'cities', 'canonical_interventions', 'normalized_programs', 'owned_programs', 'intervention_mentions']"""

if old_list not in text:
    raise RuntimeError(
        "Could not find LIST_COLUMNS definition."
    )

text = text.replace(
    old_list,
    new_list,
    1,
)

# Replace notebook-era parser with a production-safe
# parser for Parquet-loaded NumPy arrays.
pattern = re.compile(
    r"def parse_list\(x\):.*?(?=\nfor col in LIST_COLUMNS:)",
    flags=re.S,
)

replacement = r'''def parse_list(x):
    """
    Normalize list-valued fields loaded from Parquet.

    Notebook execution held these values as Python lists,
    while pyarrow/pandas may reload them as numpy.ndarray.
    """

    if x is None:
        return []

    if isinstance(x, np.ndarray):
        x = x.tolist()

    if isinstance(x, (tuple, set)):
        x = list(x)

    if isinstance(x, list):
        out = []

        def flatten(value):
            if isinstance(value, np.ndarray):
                flatten(value.tolist())

            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    flatten(item)

            elif value is None:
                return

            else:
                try:
                    if pd.isna(value):
                        return
                except (TypeError, ValueError):
                    pass

                out.append(value)

        flatten(x)

        return out

    if isinstance(x, str):
        try:
            parsed = json.loads(x)

            if isinstance(parsed, np.ndarray):
                parsed = parsed.tolist()

            if isinstance(parsed, list):
                return parse_list(parsed)

        except Exception:
            pass

    return []
'''

text, count = pattern.subn(
    replacement,
    text,
    count=1,
)

if count != 1:
    raise RuntimeError(
        f"Expected to replace one parse_list function; replaced {count}."
    )

path.write_text(
    text,
    encoding="utf-8",
)

print("PARQUET LIST NORMALIZATION PATCHED")
