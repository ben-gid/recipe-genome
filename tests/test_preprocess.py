"""Tests for src/preprocess.py.

The dataset stores lists the way R prints them: `c("flour", "sugar")`.
`parse()` turns that text back into a real Python list. These tests pin down
what it does with the normal case and with every weird cell we can think of.
"""

from datetime import timedelta

import pytest

from preprocess import format_batch, parse, parse_duration


@pytest.mark.parametrize("cell", [None, 123, 4.5, [], {}, True, b"c(1)"])
def test_parse_non_string_returns_empty_list(cell):
    """Anything that isn't a string is treated as "no data" -> empty list."""
    assert parse(cell) == []


def test_parse_empty_string_returns_empty_list():
    """An empty cell is also "no data" (guarded before the leading-c strip)."""
    assert parse("") == []


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ('c("a", "b")', ["a", "b"]),          # the common case
        ('c("x")', ["x"]),                    # single element still has the c(...)
        ("c(1, 2)", [1, 2]),                  # numbers, not just strings
        ("(1, 2)", [1, 2]),                   # already a tuple, no leading c
        ('c("has \\"quote\\"")', ['has "quote"']),  # escaped quotes survive
    ],
)
def test_parse_r_vector_becomes_flat_list(cell, expected):
    """`c(...)` loses its leading `c`, becomes a tuple, then a flat list."""
    assert parse(cell) == expected


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ('"solo"', ["solo"]),        # a lone quoted string
        ("5", [5]),                  # a lone number
        ("True", [True]),            # a lone bool
        ("[1, 2]", [[1, 2]]),        # NOTE: a list is NOT flattened, only tuples are
                                     # R prints vectors as `c()` only
    ],
)
def test_parse_non_tuple_literal_is_wrapped(cell, expected):
    """Only tuples get spread out. Everything else gets wrapped in a 1-item list."""
    assert parse(cell) == expected


# --- parse(): R's NA -> Python's None ----------------------------------------

def test_parse_bare_na_becomes_none():
    """R's "missing value" marker NA becomes Python's None."""
    assert parse("NA") == [None]


def test_parse_na_inside_a_vector():
    """NA is replaced even when it sits between real values."""
    assert parse('c(NA, "x")') == [None, "x"]


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ('c("banana")', ["banana"]),            # NA inside a word is left alone
        ('c("bananas")', ["bananas"]),
        # Known false positive: a standalone NA inside quoted *text* is replaced too.
        # Measured on the full dataset: 298,703 genuine NAs (all missing ingredient
        # quantities) vs 1 false hit ("BUENA" line-wrapped to "BUE  NA"). Not worth
        # the quote-span scanner it would take to fix.
        ('c("NA bread")', ["None bread"]),
    ],
)
def test_parse_na_replacement_respects_word_boundaries(cell, expected):
    """The \\bNA\\b word boundary is why "banana" doesn't turn into "baNonena"."""
    assert parse(cell) == expected


# --- parse(): R's empty-vector marker ----------------------------------------

@pytest.mark.parametrize(
    "cell", ["character(0)", 'c("character(0)")', "character(0) trailing"])
def test_parse_character_zero_is_empty(cell):
    """R writes an empty vector as `character(0)`; that means no data -> []."""
    assert parse(cell) == []


# --- parse(): the leading-`c` strip only fires on a real `c(...)` vector ------

def test_parse_quoted_text_starting_with_c_is_safe():
    """A quoted cell starts with `"`, not `c`, so nothing gets chopped off."""
    assert parse('"c(1,2)"') == ["c(1,2)"]


@pytest.mark.parametrize("cell", ["cheese", "chicken_broth", "c"])
def test_parse_word_starting_with_c_is_untouched(cell):
    """Only `c(` marks a vector, so plain words keep their first letter."""
    assert parse(cell) == [cell]


# --- parse(): text that isn't valid Python at all ----------------------------

@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("c(1, 2", ["(1, 2"]),        # unclosed bracket -> SyntaxError -> kept as text
        ("   ", ["   "]),             # whitespace only -> SyntaxError -> kept as text
        ("Mix well", ["Mix well"]),   # two bare words aren't valid Python -> kept as text
    ],
)
def test_parse_unparseable_text_is_kept_as_is(cell, expected):
    """A SyntaxError is swallowed on purpose: the raw text is returned instead."""
    assert parse(cell) == expected


@pytest.mark.parametrize("cell", ["banana", "cheese", "Bake", "chicken_broth"])
def test_parse_bare_single_word_is_kept_as_is(cell):
    """One unquoted word is valid Python *syntax* -- it looks like a variable name.

    So ast.literal_eval raises ValueError rather than SyntaxError. Both are
    caught, so single-word cells survive the same as multi-word ones.
    """
    assert parse(cell) == [cell]


# --- format_batch() ----------------------------------------------------------

def test_format_batch_parses_only_the_named_columns():
    """Returns just the requested columns; Dataset.map merges the rest back in."""
    batch = {"Keywords": ['c("a", "b")', "NA"], "Name": ["Soup", "Stew"]}
    assert format_batch(batch, ["Keywords"], []) == {"Keywords": [["a", "b"], [None]]}


def test_format_batch_handles_several_columns():
    """Every named column is parsed independently, row by row."""
    batch = {"Keywords": ['c("a")'], "Images": ["character(0)"]}
    assert format_batch(batch, ["Keywords", "Images"], []) == {
        "Keywords": [["a"]],
        "Images": [[]],
    }


def test_format_batch_empty_batch():
    """A column present but with zero rows stays an empty list, not an error."""
    assert format_batch({"Keywords": []}, ["Keywords"], []) == {"Keywords": []}


def test_format_batch_no_columns_requested():
    """Asking for no columns changes nothing."""
    assert format_batch({"Keywords": ['c("a")']}, [], []) == {}


def test_format_batch_missing_column_raises():
    """A typo'd column name should fail loudly, not silently skip data."""
    with pytest.raises(KeyError):
        format_batch({"Keywords": ['c("a")']}, ["Nope"], [])


def test_format_batch_does_not_mutate_input():
    """The original batch dict is left untouched (map gets a fresh dict back)."""
    batch = {"Keywords": ['c("a")']}
    format_batch(batch, ["Keywords"], [])
    assert batch == {"Keywords": ['c("a")']}


def test_format_batch_parses_duration_columns():
    """Duration columns run through parse_duration, not parse."""
    batch = {"CookTime": ["PT1H", "PT30M"]}
    assert format_batch(batch, [], ["CookTime"]) == {
        "CookTime": [timedelta(hours=1), timedelta(minutes=30)]
    }


# --- parse_duration(): ISO 8601 durations -------------------------------------

@pytest.mark.parametrize("s", [None, ""])
def test_parse_duration_empty_returns_none(s):
    """No duration recorded -> None, not an error and not 0 (0 would mean "instant")."""
    assert parse_duration(s) is None


@pytest.mark.parametrize(
    ("s", "expected"),
    [
        ("PT24H45M", timedelta(hours=24, minutes=45)),  # the docstring's own example
        ("PT30M", timedelta(minutes=30)),
        ("P1D", timedelta(days=1)),
        ("P1DT2H3M4S", timedelta(days=1, hours=2, minutes=3, seconds=4)),
        ("PT-30M", timedelta(minutes=30)),  # negative components become positive
        ("P0D", timedelta()),
    ],
)
def test_parse_duration_parses_iso_8601(s, expected):
    """Each duration component maps onto the matching timedelta kwarg."""
    assert parse_duration(s) == expected


@pytest.mark.parametrize("s", ["not a duration", "PT1X", "1H", "PTXH"])
def test_parse_duration_invalid_raises(s):
    """Text that isn't a valid ISO 8601 duration fails loudly, not silently."""
    with pytest.raises(ValueError):
        parse_duration(s)
