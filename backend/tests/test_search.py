import builtins
from datetime import timedelta

import httpx
import pytest
import weaviate
from weaviate.classes.config import DataType
from weaviate.exceptions import (
    UnexpectedStatusCodeError,
    WeaviateConnectionError,
    WeaviateStartUpError,
)
