"""
Markdown 文档解析和切分模块
提供 Markdown 文档的两层切分（标题层级 + 递归字符切分）
"""

from dataclasses import dataclass, field

import mistune
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ============== 数据结构 ==============

@dataclass
class Section:
    """Markdown section 节点"""
    title: str
    level: int  # 标题层级 1-6, 0 表示根节点
    content: str = ""  # 该 section 的正文内容（不含子 section）
    children: list["Section"] = field(default_factory=list)
    title_path: str = ""  # 标题路径，如 "一级标题 > 二级标题"


@dataclass
class Chunk:
    """文档切片"""
    content: str
    metadata: dict


# ============== Markdown 解析器 ==============

class MarkdownSectionParser:
    """
    解析 Markdown 为 section 树结构
    按标题层级（#, ##, ###...）构建文档树
    """
    
    def __init__(self):
        self.md = mistune.create_markdown(renderer=None)
    
    def parse(self, markdown_text: str) -> Section:
        """
        解析 Markdown 文本为 section 树
        Args:
            markdown_text: Markdown 文本
        Returns:
            根 Section 节点
        """
        tokens = self.md(markdown_text)
        root = Section(title="root", level=0, title_path="")
        if isinstance(tokens, list):
            self._build_tree(tokens, root)
        return root
    
    def _build_tree(self, tokens: list, root: Section):
        """构建 section 树"""
        # 使用栈来追踪当前层级的 section
        stack: list[Section] = [root]
        current_content_parts: list[str] = []
        
        for token in tokens:
            if token["type"] == "heading":
                # 保存之前积累的内容到当前 section
                if current_content_parts:
                    stack[-1].content += "\n".join(current_content_parts)
                    current_content_parts = []
                
                level = token["attrs"]["level"]
                title = self._extract_text(token["children"])
                
                # 找到合适的父节点
                while len(stack) > 1 and stack[-1].level >= level:
                    stack.pop()
                
                # 创建新 section
                parent = stack[-1]
                title_path = f"{parent.title_path} > {title}" if parent.title_path else title
                new_section = Section(
                    title=title,
                    level=level,
                    title_path=title_path
                )
                parent.children.append(new_section)
                stack.append(new_section)
            else:
                # 非标题内容，添加到当前 section
                text = self._token_to_text(token)
                if text:
                    current_content_parts.append(text)
        
        # 保存最后的内容
        if current_content_parts:
            stack[-1].content += "\n".join(current_content_parts)
    
    def _extract_text(self, children: list) -> str:
        """从 token children 中提取文本"""
        if not children:
            return ""
        parts = []
        for child in children:
            if child["type"] == "text":
                parts.append(child["raw"])
            elif "children" in child and child["children"]:
                parts.append(self._extract_text(child["children"]))
        return "".join(parts)
    
    def _token_to_text(self, token: dict) -> str:
        """将 token 转换为文本，保留代码块和表格的原始格式"""
        token_type = token["type"]
        
        if token_type == "paragraph":
            return self._extract_text(token.get("children", []))
        
        elif token_type == "code_block":
            # 保留代码块完整格式
            info = token.get("attrs", {}).get("info", "")
            raw = token.get("raw", "")
            return f"```{info}\n{raw}```"
        
        elif token_type == "fenced_code":
            info = token.get("attrs", {}).get("info", "")
            raw = token.get("raw", "")
            return f"```{info}\n{raw}```"
        
        elif token_type == "list":
            items = []
            for item in token.get("children", []):
                item_text = self._extract_text(item.get("children", []))
                items.append(f"- {item_text}")
            return "\n".join(items)
        
        elif token_type == "block_quote":
            text = self._extract_text(token.get("children", []))
            return f"> {text}"
        
        elif token_type == "table":
            # 保留表格原始结构（简化处理）
            return token.get("raw", str(token))
        
        elif token_type == "thematic_break":
            return "---"
        
        elif "children" in token:
            return self._extract_text(token["children"])
        
        elif "raw" in token:
            return token["raw"]
        
        return ""


# ============== 切分函数 ==============

def _collect_sections(section: Section, sections: list[tuple[str, str]]):
    """
    递归收集所有 section 的内容和标题路径
    Args:
        section: 当前 section
        sections: 收集结果列表 [(title_path, content), ...]
    """
    if section.content.strip():
        sections.append((section.title_path, section.content.strip()))
    
    for child in section.children:
        _collect_sections(child, sections)


def split_markdown(
    markdown_text: str,
    chunk_size: int = 600,
    chunk_overlap: int = 100,
    source_file: str = ""
) -> list[Chunk]:
    """
    两层切分 Markdown 文档
    第一层：按标题层级构建 section 树
    第二层：对每个 section 使用 RecursiveCharacterTextSplitter
    
    Args:
        markdown_text: Markdown 文本
        chunk_size: 切片大小（字符数）
        chunk_overlap: 切片重叠大小
        source_file: 源文件路径（用于元数据）
    
    Returns:
        Chunk 列表
    """
    # 第一层：解析为 section 树
    parser = MarkdownSectionParser()
    root = parser.parse(markdown_text)
    
    # 收集所有 section
    sections: list[tuple[str, str]] = []
    _collect_sections(root, sections)
    
    # 第二层：对每个 section 进行切分
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", ".", " ", ""],
        keep_separator=True
    )
    
    chunks: list[Chunk] = []
    
    for title_path, content in sections:
        # 切分内容
        split_texts = splitter.split_text(content)
        
        for i, text in enumerate(split_texts):
            chunk = Chunk(
                content=text,
                metadata={
                    "title_path": title_path,
                    "source_file": source_file,
                    "chunk_index": i,
                    "total_chunks_in_section": len(split_texts)
                }
            )
            chunks.append(chunk)
    
    return chunks

