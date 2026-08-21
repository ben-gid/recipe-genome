from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.core.config import settings, state
from app.api.routes import system, recipes

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await state.load(settings)
    yield
    
    await state.clear()

# route.tags[0] + route.name -> stable operation IDs, which is what keeps a
def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


app = FastAPI(
    lifespan=lifespan,
    generate_unique_id_function=custom_generate_unique_id
)

app.include_router(system.router)
app.include_router(recipes.router)
