from __future__ import annotations
from weaviate.outputs.query import Object
from uuid import UUID
from typing import TypedDict
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self
     
class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    
class Range(BaseModel):
    """filter db query by range. everything is inclusive.
    ge means >=
    le means <=
    """
    ge: float | None = Field(
        default=None,
        ge=0.0
    )
    le: float | None = Field(
        default=None,
        ge=0.0,
    )    
    
    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.le is not None and self.ge is not None:
            if self.le < self.ge:
                raise ValueError("Range invalid;" 
                                 "le has to be equal to or greater than ge")
        return self
    
class SearchRequestBody(BaseModel):
    query: str
    calories: Range | None = None
    protein: Range | None = None
    total_time: Range | None = None
    active_time: Range | None = None # stored in db as prep_time
    rating_floor: Range | None = None

class RecipeProps(TypedDict):
    """The Recipes properties /search reads. Names must match `config()`'s schema in src/vectorize.py.

    Handed to `collections.get()`, so it also acts as the return_properties selector:
    Weaviate stops shipping ingredients/keywords/description, which nothing here reads.
    """
    name: str
    category: str
    rating: float | None
    calories: float | None
    total_time: float | None

class RecipeHit(BaseModel):
    uuid: UUID
    name: str
    category: str
    rating: float | None 
    calories: float | None
    total_time: float | None
    score: float | None
    
    @classmethod
    def from_weaviate(cls, obj: Object[RecipeProps, None]) -> RecipeHit:
        return cls(
            uuid=obj.uuid,
            name=obj.properties["name"],
            category=obj.properties["category"],
            rating=obj.properties["rating"],
            calories=obj.properties["calories"],
            total_time=obj.properties["total_time"],
            score=obj.metadata.score
        )
    