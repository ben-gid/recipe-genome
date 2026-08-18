from datetime import timedelta
from pathlib import Path
import sys
from typing import Any

import weaviate
from weaviate.util import generate_uuid5
from weaviate.classes.config import Configure, Property, DataType
from tqdm import tqdm
from datasets import load_from_disk

DS_PATH = Path(__file__).resolve().parent.parent / "data" / "parsed-recipes"

def main():
    """Load parsed recipes, build a fresh 'Recipes' collection in Weaviate, and load it with vectorized recipe objects."""
    if not DS_PATH.exists():
        sys.exit(f"parsed recipes at: '{DS_PATH}' doesn't exist. "
                 "Run 'src/preprocess.py' to create it.")
    ds = load_from_disk(DS_PATH)
    vector_config, properties = config()

    # verify to_props matches collection properties
    schema_names = {p.name for p in properties}
    sample = to_props(ds[0]) # type: ignore
    assert sample.keys() == schema_names, (
        f"to_props drifted from schema: {sample.keys() ^ schema_names}"
    )
    with connect() as client:
        if client.collections.exists("Recipes"):
            if not verify_delete():
                sys.exit("Recipe collection untouched.")
            client.collections.delete("Recipes")

        recipes = client.collections.create(
            name="Recipes",
            vector_config=vector_config,
            properties=properties
        )

        with recipes.batch.dynamic() as batch:
            for recipe in tqdm(ds, total=len(ds)):
                batch.add_object(
                    properties=to_props(recipe), # type: ignore
                    uuid=generate_uuid5(recipe["RecipeId"]) # type: ignore
                )

        # catch failed
        if recipes.batch.failed_objects:
            print(f"failed: {len(recipes.batch.failed_objects)}")
            for failed in recipes.batch.failed_objects[:3]:
                print(f"  {failed.message}")


def connect() -> weaviate.WeaviateClient:
    """Connect to the local Weaviate, or exit with a hint if it isn't up yet."""
    try:
        return weaviate.connect_to_local()
    except weaviate.exceptions.WeaviateBaseError as e:
        sys.exit(f"Connection to Weaviate failed: {e}\n"
                 "run 'docker compose up -d' to start weaviate db")


def verify_delete(name: str = "Recipes") -> bool:
    """Ask the user to confirm deleting an existing collection before it's replaced."""
    return input(f"{name} collection already exists. Replace it? (y/n)").lower() in ("y", "yes")

def _minutes(td: timedelta | None) -> float | None:
    """Convert a duration to minutes, keeping None as "no data" instead of 0."""
    return td.total_seconds() / 60 if td else None

def to_props(recipe: dict[str, Any]) -> dict[str, Any]:
    """Map a raw dataset recipe row to the Weaviate object properties (must match `config()`'s schema)."""
    desc = recipe["Description"] or ""
    filtered_desc = "" if "food.com" in desc.lower() else desc
    return {
        "recipe_id": recipe["RecipeId"],
        "name": recipe["Name"],
        "category": recipe["RecipeCategory"] or "",
        "keywords": recipe["Keywords"],
        "ingredients": recipe["RecipeIngredientParts"],
        "description": filtered_desc,
        "rating": recipe["AggregatedRating"],
        "review_count": recipe["ReviewCount"],
        "calories": recipe["Calories"],
        "protein": recipe["ProteinContent"],
        "fat": recipe["FatContent"],
        "carbs": recipe["CarbohydrateContent"],
        "servings": recipe["RecipeServings"],
        "cook_time": _minutes(recipe["CookTime"]),
        "prep_time": _minutes(recipe["PrepTime"]),
        "total_time": _minutes(recipe["TotalTime"]),
    }
    
def config() -> tuple[Any, list]:
    """Build the Recipes collection's vector config and property schema."""
    vec_fields = ["name", "category", "keywords", "ingredients", "description"]

    vector_config = Configure.Vectors.text2vec_transformers(
        name="vector",
        source_properties=vec_fields,
        vectorize_collection_name=False,
    )

    properties = [
        Property(name='recipe_id',      data_type=DataType.INT),
        Property(name="name",           data_type=DataType.TEXT),
        Property(name="category",       data_type=DataType.TEXT),
        Property(name="keywords",       data_type=DataType.TEXT_ARRAY),
        Property(name="ingredients",    data_type=DataType.TEXT_ARRAY),
        Property(name="description",    data_type=DataType.TEXT),
        # stored, not vectorized - filterable
        Property(name="rating",         data_type=DataType.NUMBER),
        Property(name="review_count",   data_type=DataType.NUMBER),
        Property(name="calories",       data_type=DataType.NUMBER),
        Property(name="protein",        data_type=DataType.NUMBER),
        Property(name="fat",            data_type=DataType.NUMBER),
        Property(name="carbs",          data_type=DataType.NUMBER),
        Property(name="servings",       data_type=DataType.NUMBER),
        Property(name="cook_time",      data_type=DataType.NUMBER),
        Property(name="prep_time",      data_type=DataType.NUMBER),
        Property(name="total_time",     data_type=DataType.NUMBER),
    ]

    # prevent vector from building if a vec_field isn't in the collection properties
    missing = set(vec_fields) - {p.name for p in properties}
    assert not missing, f"source_properties not in schema: {missing}"

    return vector_config, properties


if __name__ == "__main__":
    main()