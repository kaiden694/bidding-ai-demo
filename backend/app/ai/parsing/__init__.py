"""文档解析服务：多解析器 fallback（unstructured → PyMuPDF → OCR）"""
from app.ai.parsing.parser import DocumentParser, ParseResult

__all__ = ["DocumentParser", "ParseResult"]
