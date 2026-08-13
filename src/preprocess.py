from pathlib import Path
import ast
import re
from typing import Any

import os

from datasets import load_dataset

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DS_PATH = DATA_DIR/ "parsed-recipes"

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

def format_batch(batch: dict[str, list[Any]], columns: list[str]):
    """Runs parse() over every cell in the given columns of one batch of rows.

    Args:
        batch (dict[str, list[Any]]): column name -> list of that column's cells
        columns (list[str]): which columns to parse

    Returns:
        dict[str, list[list[Any]]]: same columns, cells now lists
    """
    return {col: [parse(v) for v in batch[col]] for col in columns}


def main():
    """Downloads the recipe dataset, parses its list-like columns, saves it to DS_PATH."""
    raw_ds = load_dataset("untitledwebsite123/food-recipes")

    format_columns = [
        "Images", 
        "Keywords", 
        "RecipeIngredientParts",
        "RecipeIngredientQuantities",
        "RecipeInstructions",
    ]
    
    parsed_ds = raw_ds.map(
        lambda b: format_batch(b, format_columns), 
        batched=True, batch_size=100_000, 
        num_proc=(os.cpu_count() or 4) - 1
    )
    
    parsed_ds.save_to_disk(DS_PATH)
    
if __name__ == "__main__":
    main()