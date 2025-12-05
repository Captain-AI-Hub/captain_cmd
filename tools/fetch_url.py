from langchain.tools import tool
from typing import Annotated
from pydantic import Field
import requests
from bs4 import BeautifulSoup, Tag


@tool(description="Fetch and extract text content from a URL. Returns title, description, and main text content.")
def fetch_url(
    url: Annotated[str, Field(description="The URL to fetch")],
    timeout: Annotated[int, Field(default=30, description="Request timeout in seconds")] = 30,
    max_content_length: Annotated[int, Field(default=10000, description="Maximum content length to return")] = 10000
) -> str:
    """Fetch URL content and extract readable text using BeautifulSoup."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        response = requests.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        # Try to detect encoding
        if response.encoding is None or response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove script and style elements
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()
        
        # Extract title
        title = ""
        if soup.title:
            title = soup.title.get_text(strip=True)
        
        # Extract meta description
        description = ""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if isinstance(meta_desc, Tag) and meta_desc.get("content"):
            description = str(meta_desc.get("content", ""))
        
        # Try Open Graph description as fallback
        if not description:
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if isinstance(og_desc, Tag) and og_desc.get("content"):
                description = str(og_desc.get("content", ""))
        
        # Extract main content
        # Try common content containers first
        main_content = None
        for selector in ["main", "article", '[role="main"]', ".content", "#content", ".post", ".article"]:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        # If no main content found, use body
        if not main_content:
            main_content = soup.body if soup.body else soup
        
        # Get text content
        text = main_content.get_text(separator="\n", strip=True)
        
        # Clean up whitespace
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)
        
        # Truncate if too long
        if len(text) > max_content_length:
            text = text[:max_content_length] + "\n...(truncated)"
        
        # Build result
        result_parts = []
        result_parts.append(f"URL: {url}")
        if title:
            result_parts.append(f"Title: {title}")
        if description:
            result_parts.append(f"Description: {description}")
        result_parts.append(f"\nContent:\n{text}")
        
        return "\n".join(result_parts)
        
    except requests.Timeout:
        return f"Error: Request timed out after {timeout} seconds"
    except requests.RequestException as e:
        return f"Error fetching URL: {str(e)}"
    except Exception as e:
        return f"Error: {str(e)}"
