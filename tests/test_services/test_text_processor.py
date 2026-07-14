"""TextProcessor 单元测试（纯算法，无 IO）。"""

from src.services.text_processor import TextProcessor


class TestSplitTextEdgeCases:
    def test_empty_string_returns_empty_list(self):
        assert TextProcessor.split_text("") == []

    def test_none_equivalent_empty_string(self):
        # Python treats empty string as falsy — same path
        result = TextProcessor.split_text("")
        assert result == []

    def test_short_text_returns_single_chunk(self):
        text = "Hello world"
        result = TextProcessor.split_text(text, chunk_size=500)
        assert result == [text]

    def test_exact_chunk_size_returns_single_chunk(self):
        text = "x" * 500
        result = TextProcessor.split_text(text, chunk_size=500)
        assert result == [text]

    def test_one_over_chunk_size_returns_two_chunks(self):
        text = "x" * 501
        result = TextProcessor.split_text(text, chunk_size=500, overlap=0)
        assert len(result) == 2
        assert result[0] == "x" * 500
        assert result[1] == "x"


class TestSplitTextChunks:
    def test_chunks_cover_entire_text(self):
        text = "abc" * 200  # 600 chars
        chunks = TextProcessor.split_text(text, chunk_size=100, overlap=0)
        # No overlap: concatenation should equal original text
        assert "".join(chunks) == text

    def test_chunk_size_is_respected(self):
        text = "x" * 1000
        chunks = TextProcessor.split_text(text, chunk_size=200, overlap=0)
        for chunk in chunks:
            assert len(chunk) <= 200

    def test_overlap_creates_shared_content(self):
        text = "a" * 100
        chunks = TextProcessor.split_text(text, chunk_size=50, overlap=10)
        # With overlap=10, second chunk starts at 50-10=40
        assert chunks[1][:10] == chunks[0][-10:]

    def test_zero_overlap_no_repetition(self):
        text = "abcdefghij" * 10  # 100 chars
        chunks = TextProcessor.split_text(text, chunk_size=20, overlap=0)
        assert "".join(chunks) == text

    def test_last_chunk_does_not_exceed_text_length(self):
        text = "hello world"  # 11 chars
        chunks = TextProcessor.split_text(text, chunk_size=4, overlap=1)
        for chunk in chunks:
            assert len(chunk) <= 4
        # All chunks start from within the text and must be substrings of it
        for chunk in chunks:
            assert chunk in text or any(text[i : i + len(chunk)] == chunk for i in range(len(text)))

    def test_single_char_text(self):
        result = TextProcessor.split_text("a", chunk_size=10, overlap=0)
        assert result == ["a"]

    def test_chunk_size_larger_than_text(self):
        text = "short"
        result = TextProcessor.split_text(text, chunk_size=1000, overlap=50)
        assert result == [text]

    def test_unicode_text(self):
        text = "中文文本测试" * 100
        chunks = TextProcessor.split_text(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_default_params_produce_chunks_for_long_text(self):
        text = "x" * 2000
        chunks = TextProcessor.split_text(text)  # defaults: 500, 50
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 500
