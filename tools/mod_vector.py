"""
向量存储模块
提供向量数据库的存储、检索和管理功能
"""

import os
import re
from typing import Annotated, Optional
from pathlib import Path

from langchain.tools import tool
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
from pydantic import Field

from utils.utils import get_embeddings_config, get_vector_db_path
from tools.vector_markdown import split_markdown, Chunk


# ============== 嵌入模型初始化 ==============

_embeddings = None


def _get_embeddings():
    """获取或初始化嵌入模型"""
    global _embeddings
    if _embeddings is None:
        config = get_embeddings_config()
        if not config:
            raise RuntimeError("Embeddings model config not found")
                
        _embeddings = OpenAIEmbeddings(
            model=config.get("model_name", ""),
            api_key=config.get("api_key", ""),
            base_url=config.get("base_url", None)
        )
        if not _embeddings:
            raise RuntimeError("Failed to initialize embeddings model")
    return _embeddings


def _get_chroma_client(collection_name: str):
    """获取 ChromaDB 客户端"""
    vector_db_path = get_vector_db_path()
    if not vector_db_path:
        raise RuntimeError("Vector DB path not configured. Please set workspace path first.")
    
    # 确保目录存在
    os.makedirs(vector_db_path, exist_ok=True)
    
    embeddings = _get_embeddings()
    
    return Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=vector_db_path
    )


# ============== CLI 直接调用函数 ==============

def cli_store_markdown(
    file_path: str,
    collection_name: Optional[str] = None,
    chunk_size: int = 600,
    chunk_overlap: int = 100
) -> str:
    """
    CLI 直接调用：将 Markdown 文件切分并存入向量数据库
    命令格式: vector store markdown {Path} {collection_name} {chunk_size} {chunk_overlap}
    
    Args:
        file_path: Markdown 文件路径
        collection_name: 集合名称（可选，默认用文件名）
        chunk_size: 切片大小（字符数），默认 600
        chunk_overlap: 切片重叠大小，默认 100
    
    Returns:
        执行结果字符串
    """
    # 检查文件是否存在
    if not os.path.exists(file_path):
        return f"Error: File not found: {file_path}"
    
    # 读取文件
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            markdown_text = f.read()
    except Exception as e:
        return f"Error reading file: {e}"
    
    if not markdown_text.strip():
        return "Error: File is empty"
    
    # 确定 collection 名称
    if not collection_name:
        collection_name = Path(file_path).stem
    
    # 清理 collection 名称（ChromaDB 要求）
    collection_name = re.sub(r'[^a-zA-Z0-9_-]', '_', collection_name)
    if len(collection_name) < 3:
        collection_name = f"doc_{collection_name}"
    
    # 切分文档
    chunks = split_markdown(
        markdown_text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        source_file=file_path
    )
    
    if not chunks:
        return "Error: No chunks generated from the document"
    
    # 存入向量数据库
    try:
        chroma = _get_chroma_client(collection_name)
        
        texts = [chunk.content for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]
        
        chroma.add_texts(texts=texts, metadatas=metadatas)
        
        return f"Successfully stored {len(chunks)} chunks from '{file_path}' into collection '{collection_name}'"
    
    except Exception as e:
        return f"Error storing to vector DB: {e}"


def cli_list_collections() -> str:
    """
    CLI 直接调用：列出所有向量集合
    命令格式: vector list
    """
    import chromadb
    
    vector_db_path = get_vector_db_path()
    if not vector_db_path:
        return "Error: Vector DB path not configured"
    
    if not os.path.exists(vector_db_path):
        return "No vector database found. Use 'vector store markdown' to create one."
    
    try:
        client = chromadb.PersistentClient(path=vector_db_path)
        collections = client.list_collections()
        
        if not collections:
            return "No collections found in vector database."
        
        output_parts = [f"Found {len(collections)} collection(s):"]
        for col in collections:
            count = col.count()
            output_parts.append(f"  - {col.name} ({count} documents)")
        
        return "\n".join(output_parts)
    
    except Exception as e:
        return f"Error listing collections: {e}"


def cli_rag(collection_name: str, query: str, top_k: int = 5) -> tuple[bool, str, str]:
    """
    CLI 直接调用：RAG 检索并构建提示词
    命令格式: vector rag {collection_name} {query}
    
    Args:
        collection_name: 集合名称
        query: 用户查询
        top_k: 返回结果数量
    
    Returns:
        (success, context, enhanced_prompt): 成功标志、检索到的上下文、增强后的提示词
    """
    # 清理 collection 名称
    collection_name = re.sub(r'[^a-zA-Z0-9_-]', '_', collection_name)
    
    try:
        chroma = _get_chroma_client(collection_name)
        
        # 执行相似度搜索
        results = chroma.similarity_search_with_score(query, k=top_k)
        
        if not results:
            # 没有找到相关内容，直接返回原始查询
            return True, "", query
        
        # 构建上下文
        context_parts = []
        for i, (doc, score) in enumerate(results, 1):
            metadata = doc.metadata
            title_path = metadata.get("title_path", "")
            source = metadata.get("source_file", "")
            
            context_parts.append(f"[{i}] {title_path}")
            if source:
                context_parts.append(f"    Source: {source}")
            context_parts.append(f"    {doc.page_content}\n")
        
        context = "\n".join(context_parts)
        
        # 构建增强提示词
        enhanced_prompt = f"""Based on the following relevant knowledge from the knowledge base:

---
{context}
---

User Question: {query}

Please answer the question based on the above context. If the context doesn't contain relevant information, you can use your own knowledge to answer."""
        
        return True, context, enhanced_prompt
    
    except Exception as e:
        return False, "", f"Error: RAG retrieval failed: {e}"


# ============== 工具函数（供 Agent 调用） ==============

@tool(description="Store a Markdown file into vector database with hierarchical chunking")
def store_markdown(
    file_path: Annotated[str, Field(description="Path to the Markdown file to store")],
    collection_name: Annotated[Optional[str], Field(default=None, description="Collection name in vector DB. Defaults to filename without extension")] = None,
    chunk_size: Annotated[int, Field(default=600, description="Chunk size in characters (500-800 recommended)")] = 600,
    chunk_overlap: Annotated[int, Field(default=100, description="Chunk overlap in characters (50-150 recommended)")] = 100
) -> str:
    """
    将 Markdown 文件切分并存入向量数据库
    使用两层切分策略：先按标题层级分割，再用递归字符切分
    """
    return cli_store_markdown(file_path, collection_name, chunk_size, chunk_overlap)


@tool(description="Search for similar content in vector database")
def search_vectors(
    query: Annotated[str, Field(description="The query text to search for")],
    collection_name: Annotated[str, Field(description="The collection name to search in")],
    top_k: Annotated[int, Field(default=5, description="Number of results to return")] = 5
) -> str:
    """
    在向量数据库中搜索相似内容
    返回最相似的文档片段及其元数据
    """
    if not query.strip():
        return "Error: Query cannot be empty"
    
    # 清理 collection 名称
    collection_name = re.sub(r'[^a-zA-Z0-9_-]', '_', collection_name)
    
    try:
        chroma = _get_chroma_client(collection_name)
        
        # 执行相似度搜索
        results = chroma.similarity_search_with_score(query, k=top_k)
        
        if not results:
            return f"No results found in collection '{collection_name}'"
        
        # 格式化结果
        output_parts = [f"Found {len(results)} results in collection '{collection_name}':\n"]
        
        for i, (doc, score) in enumerate(results, 1):
            metadata = doc.metadata
            title_path = metadata.get("title_path", "Unknown")
            source_file = metadata.get("source_file", "Unknown")
            
            output_parts.append(f"--- Result {i} (score: {score:.4f}) ---")
            output_parts.append(f"Title Path: {title_path}")
            output_parts.append(f"Source: {source_file}")
            output_parts.append(f"Content:\n{doc.page_content}\n")
        
        return "\n".join(output_parts)
    
    except Exception as e:
        return f"Error searching vector DB: {e}"


@tool(description="List all available collections in the vector database")
def list_collections() -> str:
    """
    列出向量数据库中所有可用的集合
    """
    return cli_list_collections()
