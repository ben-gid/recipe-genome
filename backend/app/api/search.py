from fastapi import HTTPException, status
from weaviate.collections.classes.filters import _Filters
from weaviate.classes.query import Filter, MetadataQuery
import weaviate

from app.models import Range, RecipeHit, RecipeProps, SearchRequestBody

async def search_recipes(
    client: weaviate.WeaviateAsyncClient, 
    body: SearchRequestBody, 
    limit: int = 8
)-> list[RecipeHit]:
    
    filters = _build_filters(body)
    
    result = await client.collections.get("Recipes", RecipeProps).query.hybrid(
        query=body.query,
        alpha=0.75,
        filters=filters,
        limit=limit,
        return_metadata=MetadataQuery(score=True, explain_score=True)
    )
    
    return [RecipeHit.from_weaviate(obj) for obj in result.objects]
    
    
def _build_filters(request_body: SearchRequestBody) -> _Filters | None:
    ranges: dict[str, Range | None] = {
        "calories": request_body.calories,
        "protein": request_body.protein,
        "rating": request_body.rating_floor,
        "total_time": request_body.total_time,
        "prep_time": request_body.active_time,
    }
    
    clauses: list[_Filters] = []
    
    for prop, r in ranges.items():
        if r is None:
            continue
        if r.ge is not None:
            clauses.append(
                Filter.by_property(prop).greater_or_equal(r.ge))
        if r.le is not None:
            clauses.append(
                Filter.by_property(prop).less_or_equal(r.le)
            )
    
    if not clauses:
        return None        
    return Filter.all_of(clauses)