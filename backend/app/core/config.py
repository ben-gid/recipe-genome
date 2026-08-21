import weaviate
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_project_root = Path(__file__).resolve().parent.parent.parent.parent

load_dotenv()

class AppSettings(BaseSettings):
    api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env")

class AppState:
    client: weaviate.WeaviateAsyncClient | None = None

    async def load(self, settings: AppSettings) -> None:
        # use_async_with_local() is sync and returns an unconnected client —
        # awaiting it is the type error; connect() is the awaitable part.
        self.client = weaviate.use_async_with_local()
        await self.client.connect()

    async def clear(self) -> None:
        if self.client:
            await self.client.close()
            self.client = None

settings = AppSettings()
state = AppState()