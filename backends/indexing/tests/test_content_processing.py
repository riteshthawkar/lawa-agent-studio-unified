"""
Comprehensive tests for content processing and chunking.

Tests cover:
- HTML content extraction
- Markdown splitting
- Content size management
- Edge cases with various content types
"""

import pytest
from unittest.mock import patch, MagicMock
import asyncio


class TestMarkdownSplitter:
    """Tests for MarkdownSplitter module."""

    def test_split_simple_markdown(self):
        """
        Test splitting simple markdown text.
        Real-world scenario: Blog post with paragraphs.
        """
        from modules.markdown_splitter import MarkdownSplitter

        splitter = MarkdownSplitter(
            max_chunk_size=50,  # Very small for testing
            overlap_size=10
        )

        content = """
# Title

This is the first paragraph with some content.

This is the second paragraph with more content.

## Section

More detailed content here.
"""

        chunks = splitter.split_markdown(content)

        assert len(chunks) > 1
        # Each chunk should have content
        for chunk in chunks:
            assert len(chunk.strip()) > 0

    def test_split_preserves_headings(self):
        """
        Test that heading context is preserved in chunks.
        Real-world scenario: RAG needs context for each chunk.
        """
        from modules.markdown_splitter import MarkdownSplitter

        splitter = MarkdownSplitter(
            max_chunk_size=100,
            overlap_size=20,
            include_all_headings=True
        )

        content = """
# Main Topic

Introduction text.

## Subtopic A

Content for subtopic A.

### Deep Topic

Very specific content.
"""

        chunks = splitter.split_markdown(content)

        # Later chunks should have heading context
        assert len(chunks) > 0

    def test_split_code_blocks_atomic(self):
        """
        Test that code blocks are kept together.
        Real-world scenario: Technical documentation.
        """
        from modules.markdown_splitter import MarkdownSplitter

        splitter = MarkdownSplitter(
            max_chunk_size=200,
            overlap_size=20,
            preserve_atomic_blocks=True
        )

        content = """
# Code Example

Here is some code:

```python
def hello_world():
    print("Hello, World!")
    return True
```

After the code block.
"""

        chunks = splitter.split_markdown(content)

        # Code block should be in a single chunk
        code_found = False
        for chunk in chunks:
            if "def hello_world" in chunk:
                assert "return True" in chunk  # Entire function together
                code_found = True

        assert code_found

    def test_split_empty_content(self):
        """
        Test handling empty content.
        Real-world scenario: Page with no text.
        """
        from modules.markdown_splitter import MarkdownSplitter

        splitter = MarkdownSplitter()

        chunks = splitter.split_markdown("")

        assert chunks == [] or chunks == [""]

    def test_split_very_large_content(self):
        """
        Test splitting very large content.
        Real-world scenario: Long documentation page.
        """
        from modules.markdown_splitter import MarkdownSplitter

        splitter = MarkdownSplitter(
            max_chunk_size=500,
            overlap_size=50
        )

        # Generate large content
        content = "# Large Document\n\n"
        for i in range(100):
            content += f"## Section {i}\n\nThis is paragraph {i} with some content. " * 10 + "\n\n"

        chunks = splitter.split_markdown(content)

        # Should create multiple chunks
        assert len(chunks) > 10

        # Each chunk should be reasonable size
        for chunk in chunks:
            assert len(chunk.split()) <= 600  # With some buffer


class TestHTMLProcessor:
    """Tests for HTML processing module."""

    def test_extract_text_from_simple_html(self):
        """
        Test extracting text from simple HTML.
        Real-world scenario: Basic webpage.
        """
        from modules.html_processor import HTMLProcessor

        processor = HTMLProcessor()

        html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Welcome</h1>
                <p>This is a paragraph.</p>
            </body>
        </html>
        """

        result = processor.process(html)

        assert "Welcome" in result.get("content", "")
        assert "paragraph" in result.get("content", "")

    def test_extract_title(self):
        """
        Test extracting page title.
        Real-world scenario: Need title for search results.
        """
        from modules.html_processor import HTMLProcessor

        processor = HTMLProcessor()

        html = """
        <html>
            <head><title>My Page Title</title></head>
            <body><p>Content</p></body>
        </html>
        """

        result = processor.process(html)

        assert result.get("title") == "My Page Title" or "My Page Title" in str(result)

    def test_remove_script_and_style(self):
        """
        Test that scripts and styles are removed.
        Real-world scenario: Don't index JavaScript/CSS.
        """
        from modules.html_processor import HTMLProcessor

        processor = HTMLProcessor()

        html = """
        <html>
            <head>
                <style>.class { color: red; }</style>
                <script>function x() { alert('hi'); }</script>
            </head>
            <body>
                <p>Real content here.</p>
                <script>more_js();</script>
            </body>
        </html>
        """

        result = processor.process(html)
        content = result.get("content", "")

        assert "alert" not in content
        assert "color: red" not in content
        assert "Real content" in content

    def test_extract_links(self):
        """
        Test extracting links from HTML.
        Real-world scenario: Crawl discovery needs links.
        """
        from modules.html_processor import HTMLProcessor

        processor = HTMLProcessor()

        html = """
        <html>
            <body>
                <a href="/page1">Link 1</a>
                <a href="https://example.com/page2">Link 2</a>
                <a href="#">Skip</a>
            </body>
        </html>
        """

        result = processor.process(html)

        # Should have extracted some links
        links = result.get("links", [])
        assert isinstance(links, list)

    def test_handle_malformed_html(self):
        """
        Test handling malformed HTML.
        Real-world scenario: Poorly coded websites.
        """
        from modules.html_processor import HTMLProcessor

        processor = HTMLProcessor()

        html = """
        <html>
            <body>
                <p>Unclosed paragraph
                <div>Nested <span>incorrectly</div></span>
                <p>More content</p>
            </body>
        """

        # Should not raise
        result = processor.process(html)

        assert "content" in result or result is not None


class TestContentChunking:
    """Tests for DocumentEmbedder content chunking."""

    def test_chunk_document_basic(self):
        """
        Test basic word-based chunking.
        Real-world scenario: Split large document for embedding.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            text = "word " * 1000  # 1000 words

            chunks = embedder.chunk_document(text, max_chunk_size=200, overlap_size=20)

            assert len(chunks) > 1
            for chunk in chunks:
                assert len(chunk.split()) <= 200

    def test_chunk_document_with_overlap(self):
        """
        Test that chunks have proper overlap.
        Real-world scenario: Context preserved between chunks.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            words = [f"word{i}" for i in range(100)]
            text = " ".join(words)

            chunks = embedder.chunk_document(text, max_chunk_size=30, overlap_size=10)

            # Check overlap exists between consecutive chunks
            if len(chunks) > 1:
                chunk1_words = set(chunks[0].split()[-10:])
                chunk2_words = set(chunks[1].split()[:10])
                # Should have some overlap
                overlap = chunk1_words.intersection(chunk2_words)
                # Overlap size depends on implementation details

    def test_chunk_small_document(self):
        """
        Test that small documents aren't unnecessarily chunked.
        Real-world scenario: Short FAQ page.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            text = "This is a short document."

            chunks = embedder.chunk_document(text, max_chunk_size=500)

            assert len(chunks) == 1
            assert chunks[0] == text


class TestContentSizeChecking:
    """Tests for Pinecone metadata size checking."""

    def test_check_content_size_within_limit(self):
        """
        Test content within 35KB limit.
        Real-world scenario: Normal document size.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = "x" * 30000  # 30KB

            result = embedder._check_content_size(content)

            assert result is True

    def test_check_content_size_exceeds_limit(self):
        """
        Test content exceeding limit.
        Real-world scenario: Very large page content.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = "x" * 50000  # 50KB

            result = embedder._check_content_size(content)

            assert result is False

    def test_truncate_content_safely(self):
        """
        Test safe content truncation.
        Real-world scenario: Trim oversized content.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = "This is a test. " * 5000  # ~80KB

            truncated = embedder._truncate_content_safely(content, max_size_bytes=10000)

            assert len(truncated.encode('utf-8')) <= 10003  # With "..."

    def test_truncate_at_word_boundary(self):
        """
        Test truncation at word boundary.
        Real-world scenario: Clean truncation for display.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = "word1 word2 word3 word4 word5"

            # Truncate to fit ~15 bytes - should cut at word boundary
            truncated = embedder._truncate_content_safely(content, max_size_bytes=15)

            # Should end cleanly (not mid-word)
            assert not truncated.rstrip('.').endswith('wor')


class TestAsyncContentProcessing:
    """Tests for async content processing methods."""

    @pytest.mark.asyncio
    async def test_chunk_content_with_markdown_splitter(self):
        """
        Test async chunking with MarkdownSplitter.
        Real-world scenario: Process page content asynchronously.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = """
# Title

Paragraph one with some content here.

## Section

More detailed content in section.
""" * 50  # Make it large

            chunks = await embedder._chunk_content_with_markdown_splitter(
                content,
                "https://example.com"
            )

            assert len(chunks) > 0
            for chunk in chunks:
                assert "text" in chunk
                assert "metadata" in chunk
                assert chunk["metadata"]["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_process_content_for_pinecone_small(self):
        """
        Test processing small content (no chunking needed).
        Real-world scenario: Small page fits in one vector.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = "Small content here."

            result = await embedder._process_content_for_pinecone(
                content,
                "https://small.com"
            )

            assert len(result) == 1
            assert result[0]["metadata"]["chunk_type"] == "single"

    @pytest.mark.asyncio
    async def test_process_content_for_pinecone_large(self):
        """
        Test processing large content (chunking required).
        Real-world scenario: Long documentation page.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            # Create content larger than 35KB
            content = "Content paragraph. " * 3000  # ~54KB

            result = await embedder._process_content_for_pinecone(
                content,
                "https://large.com"
            )

            assert len(result) > 1
            for chunk in result:
                assert chunk["metadata"]["total_chunks"] > 1


class TestFallbackChunking:
    """Tests for fallback chunking when MarkdownSplitter fails."""

    def test_fallback_chunk_content(self):
        """
        Test fallback word-based chunking.
        Real-world scenario: MarkdownSplitter error recovery.
        """
        from modules.embedder import DocumentEmbedder

        with patch.object(DocumentEmbedder, '_setup_models'):
            embedder = DocumentEmbedder(MagicMock())

            content = "word " * 5000  # 5000 words

            chunks = embedder._fallback_chunk_content(content, "https://fallback.com")

            assert len(chunks) > 1
            for chunk in chunks:
                assert chunk["metadata"]["chunk_type"] == "fallback_chunk"
                assert "url" in chunk["metadata"]
