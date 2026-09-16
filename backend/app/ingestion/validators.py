from collections.abc import Iterable


def validate_required_columns(
    actual_columns: Iterable[str],
    required_columns: set[str],
) -> None:
    actual = set(actual_columns)
    missing = required_columns - actual

    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(
            f"Missing required CSV columns: {missing_list}"
        )