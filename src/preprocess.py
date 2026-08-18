from pathlib import Path
from datetime import timedelta
import ast
import re
from typing import Any

import os

from datasets import load_dataset

# CookTime/PrepTime/TotalTime are ISO 8601 *durations* (e.g. "PT24H45M"),
# some rows have negative components (e.g. "PT-30M"), hence the -? in each group.
ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<days>-?\d+)D)?"
    r"(?:T(?:(?P<hours>-?\d+)H)?(?:(?P<minutes>-?\d+)M)?(?:(?P<seconds>-?\d+)S)?)?$"
)

DS_PATH = Path(__file__).resolve().parent.parent / "data" / "parsed-recipes"

def parse(cell: Any) -> list[Any]:
    """parses ds cells (R code) into python list. 
    if v is not a str an empty list is returned

    Args:
        cell (Any): cell to parse

    Returns:
        list[Any]: parsed cell as a list
    """
    if not isinstance(cell, str) or not cell:
        return []
    if cell.startswith("c("):
        cell = cell[1:]
    # use re with word boundary for words like "banana"
    cell = re.sub(r"\bNA\b", "None", cell)
    if "character(0)" in cell:
        return []
    try:
        cell = ast.literal_eval(cell)
    except (SyntaxError, ValueError):
        pass
    return list(cell) if isinstance(cell, tuple) else [cell]

def parse_duration(s: str) -> timedelta:
    """converts ISO 8601 durations - not datetimes- into datetime.timedelta

    Args:
        s (str): ISO 8601 durations 

    Raises:
        ValueError: if s doesn't match ISO_DURATION_RE

    Returns:
        timedelta: parsed duration as timedelta
    """
    if not s:
        return timedelta(seconds=0)
    m = ISO_DURATION_RE.match(s)
    if not m:
        raise ValueError(f"Invalid ISO 8601 duration: {s!r}")
    # take absolute value for the 3 negative (probably corrupted) durations in the ds
    return abs(timedelta(**{k: int(v) for k, v in m.groupdict().items() if v}))

def format_batch(
    batch: dict[str, list[Any]], 
    reg_columns: list[str], 
    dur_columns: list[str]
) -> dict[str, list[list[Any]] | list[timedelta]]:
    """Runs parse() over every cell in the named columns of one batch of rows."""
    reg = {col: [parse(v) for v in batch[col]] for col in reg_columns}
    dur = {col: [parse_duration(v) for v in batch[col]] for col in dur_columns}
        
    return reg | dur


def main():
    """Downloads the recipe dataset, parses its list-like columns, saves it to DS_PATH."""
    raw_ds = load_dataset("untitledwebsite123/food-recipes", split="train")

    reg_format_columns = [
        "Images", 
        "Keywords", 
        "RecipeIngredientParts",
        "RecipeIngredientQuantities",
        "RecipeInstructions",
    ]
    
    dur_format_columns = ["CookTime", "PrepTime", "TotalTime"]
    
    parsed_ds = raw_ds.map(
        lambda b: format_batch(b, reg_format_columns, dur_format_columns), 
        batched=True, batch_size=2_000, 
        num_proc=(os.cpu_count() or 4) - 1
    )
    
    parsed_ds.save_to_disk(DS_PATH)
    
if __name__ == "__main__":
    main()