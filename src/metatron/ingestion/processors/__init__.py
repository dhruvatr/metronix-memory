"""Document processors for various file formats."""

from metatron.ingestion.processors.dates import extract_date_from_text, extract_date_range
from metatron.ingestion.processors.html import process_html
from metatron.ingestion.processors.office import OfficeProcessor, extract_text_from_docx
from metatron.ingestion.processors.pdf import PdfProcessor, extract_text_from_pdf
from metatron.ingestion.processors.tabular import is_tabular_file, process_tabular_file
from metatron.ingestion.processors.text import TextProcessor
from metatron.ingestion.processors.titles import (
    extract_title_from_body,
    extract_title_from_markdown,
)
from metatron.ingestion.processors.translation import (
    is_english,
    is_russian,
    translate_to_english,
    translate_to_russian,
)

__all__ = [
    "process_html",
    "extract_date_from_text",
    "extract_date_range",
    "process_tabular_file",
    "is_tabular_file",
    "extract_title_from_body",
    "extract_title_from_markdown",
    "is_russian",
    "is_english",
    "translate_to_english",
    "translate_to_russian",
    "TextProcessor",
    "PdfProcessor",
    "extract_text_from_pdf",
    "OfficeProcessor",
    "extract_text_from_docx",
]
