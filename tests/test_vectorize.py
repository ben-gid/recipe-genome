"""Tests for src/vectorize.py.

Only the pure, offline parts are tested: turning a dataset row into Weaviate
properties, the schema definition, and the delete confirmation prompt.
`main()` needs a running Weaviate server and the saved dataset, so it is left
to integration testing.
"""

import builtins

import httpx
import pytest
import weaviate
from weaviate.classes.config import DataType
from weaviate.exceptions import (
    UnexpectedStatusCodeError,
    WeaviateConnectionError,
    WeaviateStartUpError,
)

from vectorize import config, connect, to_props, verify_delete


def make_recipe(**overrides):
    """Build a complete dataset row, with any field overridden for one test."""
    recipe = {
        "RecipeId": 38,
        "Name": "Low-Fat Berry Blue Frozen Dessert",
        "RecipeCategory": "Frozen Desserts",
        "Keywords": ["Dessert", "Low Protein"],
        "RecipeIngredientParts": ["blueberries", "sugar"],
        "Description": "Make and share this recipe.",
        "AggregatedRating": 4.5,
        "ReviewCount": 4.0,
        "Calories": 170.9,
        "ProteinContent": 3.2,
        "FatContent": 2.5,
        "CarbohydrateContent": 37.1,
        "RecipeServings": 4.0,
    }
    return recipe | overrides


# --- to_props(): the schema-drift guard main() relies on ---------------------

def test_to_props_keys_match_schema_exactly():
    """The row-to-object mapping and the collection schema must not drift apart.

    main() asserts this at runtime against row 0; this runs it without a server.
    """
    _, properties = config()
    assert to_props(make_recipe()).keys() == {p.name for p in properties}


def test_to_props_passes_values_through_unchanged():
    """Every field lands under its new name with its value untouched."""
    props = to_props(make_recipe())
    assert props["recipe_id"] == 38
    assert props["name"] == "Low-Fat Berry Blue Frozen Dessert"
    assert props["keywords"] == ["Dessert", "Low Protein"]
    assert props["ingredients"] == ["blueberries", "sugar"]
    assert props["rating"] == 4.5
    assert props["review_count"] == 4.0
    assert props["calories"] == 170.9
    assert props["protein"] == 3.2
    assert props["fat"] == 2.5
    assert props["carbs"] == 37.1
    assert props["servings"] == 4.0


# --- to_props(): missing values ---------------------------------------------

@pytest.mark.parametrize("empty", [None, ""])
def test_to_props_missing_text_becomes_empty_string(empty):
    """Weaviate TEXT fields get "" instead of None, so nothing blows up on insert."""
    props = to_props(make_recipe(Description=empty, RecipeCategory=empty))
    assert props["description"] == ""
    assert props["category"] == ""


def test_to_props_leaves_missing_numbers_as_none():
    """Numbers are NOT defaulted -- None stays None, so unrated recipes stay unrated."""
    props = to_props(make_recipe(AggregatedRating=None, RecipeServings=None))
    assert props["rating"] is None
    assert props["servings"] is None


def test_to_props_missing_column_raises():
    """A renamed or absent dataset column should fail loudly, not insert junk."""
    recipe = make_recipe()
    del recipe["Calories"]
    with pytest.raises(KeyError):
        to_props(recipe)


# --- to_props(): the food.com spam filter -----------------------------------

@pytest.mark.parametrize(
    "desc",
    [
        "Make and share this recipe from Food.com.",
        "from FOOD.COM",                       # filter is case-insensitive
        "food.com",                            # the whole description
        "see food.com for more",               # buried mid-sentence
    ],
)
def test_to_props_drops_descriptions_mentioning_food_com(desc):
    """Boilerplate site plugs are dropped so they don't pollute the vectors."""
    assert to_props(make_recipe(Description=desc))["description"] == ""


@pytest.mark.parametrize(
    "desc",
    [
        "A great summer dessert.",
        "Good food, come and get it.",   # "food" and "com" apart -> kept
        "Serve with foodcom sauce.",     # no dot -> kept
    ],
)
def test_to_props_keeps_real_descriptions(desc):
    """Only the literal "food.com" is filtered; normal text survives intact."""
    assert to_props(make_recipe(Description=desc))["description"] == desc


# --- verify_delete(): the "are you sure?" prompt ----------------------------

@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", "Yes"])
def test_verify_delete_accepts_yes(monkeypatch, answer):
    """Only a clear yes (any capitalisation) approves dropping the collection."""
    monkeypatch.setattr(builtins, "input", lambda _: answer)
    assert verify_delete() is True


@pytest.mark.parametrize("answer", ["n", "N", "no", "", "   ", "maybe", "ye", "yep", "1"])
def test_verify_delete_rejects_anything_else(monkeypatch, answer):
    """Anything unclear counts as no -- deleting data must be opt-in."""
    monkeypatch.setattr(builtins, "input", lambda _: answer)
    assert verify_delete() is False


def test_verify_delete_prompt_names_the_collection(monkeypatch):
    """The user must see *which* collection is about to be replaced."""
    seen = []
    monkeypatch.setattr(builtins, "input", lambda prompt: seen.append(prompt) or "n")
    verify_delete("Recipes")
    assert "Recipes" in seen[0]


# --- connect(): the "is Weaviate actually up?" guard ------------------------

@pytest.mark.parametrize(
    "error",
    [
        WeaviateConnectionError("refused"),        # nothing listening at all
        WeaviateStartUpError("not ready"),         # server up but still booting
        UnexpectedStatusCodeError("meta", httpx.Response(404)),  # something else on the port
    ],
)
def test_connect_exits_when_weaviate_is_unreachable(monkeypatch, error):
    """Every flavour of "not usable yet" exits cleanly instead of a traceback."""
    monkeypatch.setattr(weaviate, "connect_to_local", lambda: (_ for _ in ()).throw(error))
    with pytest.raises(SystemExit) as exit_info:
        connect()
    assert "docker compose up -d" in str(exit_info.value)


def test_connect_returns_the_client_when_weaviate_is_up(monkeypatch):
    """The happy path hands the client straight back for main()'s `with`."""
    sentinel = object()
    monkeypatch.setattr(weaviate, "connect_to_local", lambda: sentinel)
    assert connect() is sentinel


# --- config(): the collection schema ----------------------------------------

def test_config_vector_sources_are_real_properties():
    """Weaviate would silently vectorize nothing if a source field didn't exist."""
    vector_config, properties = config()
    assert set(vector_config.properties or []) <= {p.name for p in properties}


def test_config_vectorizes_the_text_fields():
    """These five fields are what a search query is actually matched against."""
    vector_config, _ = config()
    assert vector_config.properties == [
        "name", "category", "keywords", "ingredients", "description",
    ]


def test_config_does_not_vectorize_the_collection_name():
    """The word "Recipes" shouldn't nudge every vector in the same direction."""
    vector_config, _ = config()
    assert vector_config.vectorizer.vectorizeClassName is False


def test_config_property_names_are_unique():
    """A duplicate name would make Weaviate reject the collection at create time."""
    names = [p.name for p in config()[1]]
    assert len(names) == len(set(names))


def test_config_property_types():
    """Numbers must be NUMBER (filterable/sortable) and lists must be TEXT_ARRAY."""
    types = {p.name: p.dataType for p in config()[1]}
    assert types == {
        "recipe_id": DataType.INT,
        "name": DataType.TEXT,
        "category": DataType.TEXT,
        "keywords": DataType.TEXT_ARRAY,
        "ingredients": DataType.TEXT_ARRAY,
        "description": DataType.TEXT,
        "rating": DataType.NUMBER,
        "review_count": DataType.NUMBER,
        "calories": DataType.NUMBER,
        "protein": DataType.NUMBER,
        "fat": DataType.NUMBER,
        "carbs": DataType.NUMBER,
        "servings": DataType.NUMBER,
    }
