"""M6 TextProcessor — 文本切分工具。"""


class TextProcessor:
    @staticmethod
    def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start = end - overlap
        return chunks
