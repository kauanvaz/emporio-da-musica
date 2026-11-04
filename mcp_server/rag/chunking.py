import re

from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from mcp_server.domain.models import PolicyChunk


class PolicyChunkingError(RuntimeError):
    pass


_HEADING_RE = re.compile(r"^(#{1,6})(\s+)(.*)$")


def chunk_policy_manual(
    markdown: str,
    document_id: str,
    max_chunk_chars: int,
    chunk_overlap_chars: int,
) -> list[PolicyChunk]:
    if max_chunk_chars < 1:
        raise PolicyChunkingError("RAG_MAX_CHUNK_CHARS must be greater than zero.")
    if chunk_overlap_chars < 0 or chunk_overlap_chars >= max_chunk_chars:
        raise PolicyChunkingError(
            "RAG_CHUNK_OVERLAP_CHARS must be non-negative and smaller than "
            "RAG_MAX_CHUNK_CHARS."
        )

    cleaned = _strip_bold_from_headings(markdown)
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
        ],
        strip_headers=True,
    )
    sections = splitter.split_text(cleaned)

    chunks: list[PolicyChunk] = []
    for section_number, section in enumerate(sections):
        section_path = _section_path(section)
        text = section.page_content.strip()
        if not section_path or not text:
            continue

        if len(text) <= max_chunk_chars:
            chunks.append(
                PolicyChunk(
                    chunk_id=_chunk_id(document_id, section_path, section_number, 0),
                    section=section_path,
                    text=text,
                )
            )
            continue

        chunks.extend(
            _split_large_section(
                text,
                section_path=section_path,
                document_id=document_id,
                section_number=section_number,
                max_chunk_chars=max_chunk_chars,
                chunk_overlap_chars=chunk_overlap_chars,
            )
        )

    if not chunks:
        raise PolicyChunkingError("Policy manual did not produce any chunks.")
    return chunks


def _strip_bold_from_headings(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match is None:
            lines.append(line)
            continue
        lines.append(
            f"{match.group(1)}{match.group(2)}{match.group(3).replace('**', '')}"
        )
    return "\n".join(lines)


def _section_path(section: Document) -> str:
    keys = ("h2", "h3") if section.metadata.get("h2") else ("h1", "h2", "h3")
    levels = [
        str(section.metadata[key]).strip() for key in keys if section.metadata.get(key)
    ]
    return " > ".join(level for level in levels if level)


def _split_large_section(
    text: str,
    *,
    section_path: str,
    document_id: str,
    section_number: int,
    max_chunk_chars: int,
    chunk_overlap_chars: int,
) -> list[PolicyChunk]:
    prefix = f"{section_path}\n\n"
    available_chars = max_chunk_chars - len(prefix)
    if available_chars < 2:
        raise PolicyChunkingError(
            f"Section path is too long for RAG_MAX_CHUNK_CHARS: {section_path!r}."
        )

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=available_chars,
        chunk_overlap=min(chunk_overlap_chars, available_chars - 1),
        length_function=len,
    )

    chunks: list[PolicyChunk] = []
    for part_number, part in enumerate(splitter.split_text(text)):
        part = part.strip()
        if not part:
            continue
        chunk_text = f"{prefix}{part}"
        if len(chunk_text) > max_chunk_chars:
            raise PolicyChunkingError(
                "Policy chunk exceeds RAG_MAX_CHUNK_CHARS after splitting "
                f"section {section_path!r}."
            )
        chunks.append(
            PolicyChunk(
                chunk_id=_chunk_id(
                    document_id,
                    section_path,
                    section_number,
                    part_number,
                ),
                section=section_path,
                text=chunk_text,
            )
        )
    return chunks


def _chunk_id(
    document_id: str,
    section_path: str,
    section_number: int,
    part_number: int,
) -> str:
    return f"{document_id}::{section_path}::{section_number}::{part_number}"


__all__ = ["PolicyChunkingError", "chunk_policy_manual"]
