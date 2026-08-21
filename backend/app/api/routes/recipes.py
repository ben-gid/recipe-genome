from fastapi import APIRouter, Request, HTTPException, status
from app.models import RecipeHit, SearchRequestBody
from app.api.search import search_recipes
from app.core.config import settings, state

router = APIRouter(tags=["Recipes"])

@router.post(path="/search", response_model=list[RecipeHit])
async def search(request: Request, body: SearchRequestBody):
    if state.client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Weaviate client not loaded; try again later"
        )
    return await search_recipes(state.client, body=body)