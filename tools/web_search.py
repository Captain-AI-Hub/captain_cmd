from typing import Literal, Annotated
from tavily import TavilyClient
from utils.utils import get_model_config
from langchain.tools import tool
from pydantic import Field

_tavily_client = None

@tool(description="Run a web search to find information")
def internet_search(
    query: Annotated[str, Field(description="The query to search for")],
    max_results: Annotated[int, Field(default=5, description="The maximum number of results to return")],
    topic: Annotated[Literal["general", "news", "finance"], Field(default="general", description="The topic of the search")],
    include_raw_content: Annotated[bool, Field(default=False, description="Whether to include raw content in the results")],
    include_answer: Annotated[bool, Field(default=False, description="Whether to include answer in the results")]
):
    global _tavily_client
    if _tavily_client is None:
        model_config = get_model_config()
        if model_config == "Error: toml_path is None":
            raise RuntimeError("Failed to load model config")
        tavily_api_key = model_config.get("tavily_api_key", "")
        if not tavily_api_key:
            raise RuntimeError("Tavily API key is not set")
        _tavily_client = TavilyClient(api_key=tavily_api_key)

    return _tavily_client.search(
        query,
        max_results=max_results,
        include_raw_content=include_raw_content,
        include_answer=include_answer,
        topic=topic,
    )

