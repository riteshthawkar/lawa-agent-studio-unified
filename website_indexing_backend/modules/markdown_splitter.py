import re

class MarkdownSplitter:
    def __init__(self, max_chunk_size=2000, overlap_size=200, preserve_atomic_blocks=True, include_all_headings=True, max_heading_depth=10):
        """
        Initialize the MarkdownSplitter optimized for RAG applications.
        
        Args:
            max_chunk_size (int): Maximum number of words allowed in each chunk
            overlap_size (int): Number of words to overlap between chunks (0 for no overlap)
            preserve_atomic_blocks (bool): Whether to keep code blocks, tables, and lists as atomic units
            include_all_headings (bool): Whether to include all ancestor headings or just select ones
            max_heading_depth (int): Maximum depth of headings to include in prefix
        """
        self.max_chunk_size = max_chunk_size
        self.overlap_size = overlap_size
        self.preserve_atomic_blocks = preserve_atomic_blocks
        self.include_all_headings = include_all_headings
        self.max_heading_depth = max_heading_depth
        
    def split_markdown(self, content, debug=False):
        """
        Split markdown content with optional debugging.
        
        Args:
            content (str): The markdown content to split
            debug (bool): Whether to include debug information
            
        Returns:
            tuple: (chunks, stats) where stats contains information about the chunking process
        """
        stats = {
            "total_chunks": 0,
            "avg_chunk_size": 0,
            "content_length": len(content),
            "word_count": 0,
            "breaking_points": []
        }
        # Add input validation and error handling
        if not content or not isinstance(content, str):
            return [] if not debug else ([], stats)
        
        try:
            lines = content.splitlines()
            chunks = []
            current_chunk = []
            current_word_count = 0
            
            # Track heading hierarchy
            heading_stack = []  # [(level, heading_text), ...]
            
            # Track block state to avoid breaking within blocks
            in_block_element = False
            block_type = None
            block_content = []
            
            # Track paragraph content for semantic chunking
            paragraph_buffer = []
            
            # For overlapping: keep track of recent content
            recent_content = []  # List of recent elements to use for overlap
            
            i = 0
            while i < len(lines):
                line = lines[i]
                line_word_count = len(re.findall(r'\S+', line))
                
                # Check if line is a heading
                heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
                if heading_match:
                    level = len(heading_match.group(1))
                    heading_text = heading_match.group(2)
                    
                    # Process any buffered paragraph content before handling the heading
                    if paragraph_buffer:
                        self._process_paragraph_buffer(paragraph_buffer, current_chunk, heading_stack, chunks, recent_content)
                        paragraph_buffer = []
                    
                    # Update heading stack - remove any headings of same or higher level
                    heading_stack = [h for h in heading_stack if h[0] < level]
                    heading_stack.append((level, heading_text))
                    
                    # Headings are natural break points for significant headings (level 1-3)
                    if current_word_count > 0 and level <= 3 and current_word_count >= self.max_chunk_size / 2:
                        # Create a new chunk with the current content
                        chunks.append(self._create_chunk(current_chunk))
                        
                        # Reset content tracking
                        if self.overlap_size > 0:
                            self._update_recent_content(current_chunk, recent_content)
                        
                        # Start new chunk with heading context and overlap
                        current_chunk = self._create_minimal_heading_prefix(heading_stack)
                        if self.overlap_size > 0 and recent_content:
                            current_chunk.extend(self._get_overlap_content(recent_content))
                        
                        current_word_count = self._count_words(current_chunk)
                    
                    # Add the heading to the current chunk
                    current_chunk.append(line)
                    current_word_count += line_word_count
                    
                    in_block_element = False
                    block_type = None
                    
                # Handle code blocks as atomic units
                elif line.strip().startswith('```'):
                    if not in_block_element:
                        # Starting a new code block
                        in_block_element = True
                        block_type = 'code'
                        block_content = [line]
                    else:
                        # Ending a code block
                        block_content.append(line)
                        
                        # Check if adding this block would exceed the chunk size
                        block_word_count = self._count_words(block_content)
                        
                        if current_word_count + block_word_count > self.max_chunk_size and current_word_count > 0:
                            # Current chunk is already substantial, start a new one with this block
                            chunks.append(self._create_chunk(current_chunk))
                            
                            # Reset content tracking for overlap
                            if self.overlap_size > 0:
                                self._update_recent_content(current_chunk, recent_content)
                            
                            # New chunk with headings and overlap
                            current_chunk = self._create_minimal_heading_prefix(heading_stack)
                            if self.overlap_size > 0 and recent_content:
                                current_chunk.extend(self._get_overlap_content(recent_content))
                                
                            current_word_count = self._count_words(current_chunk)
                        
                        # Add the entire code block to the current chunk
                        current_chunk.extend(block_content)
                        current_word_count += block_word_count
                        
                        in_block_element = False
                        block_type = None
                        block_content = []
                
                elif in_block_element and block_type == 'code':
                    # Accumulate code block content
                    block_content.append(line)
                
                # Handle blockquotes (moved here from outside the if-elif chain)
                elif line.strip().startswith('>'):
                    if not in_block_element or block_type != 'blockquote':
                        # Process any buffered paragraph content
                        if paragraph_buffer:
                            self._process_paragraph_buffer(paragraph_buffer, current_chunk, heading_stack, chunks, recent_content)
                            paragraph_buffer = []
                        
                        # Starting a new blockquote
                        if not in_block_element:
                            in_block_element = True
                            block_type = 'blockquote'
                            block_content = []
                    
                    # Add the blockquote line
                    block_content.append(line)
                
                # Handle lists as semantic units
                elif re.match(r'^\s*[-*+]\s', line) or re.match(r'^\s*\d+\.\s', line):
                    if not in_block_element or block_type != 'list':
                        # Process any buffered paragraph content
                        if paragraph_buffer:
                            self._process_paragraph_buffer(paragraph_buffer, current_chunk, heading_stack, chunks, recent_content)
                            paragraph_buffer = []
                        
                        # Starting a new list or continuing list items
                        if not in_block_element:
                            in_block_element = True
                            block_type = 'list'
                            block_content = []
                    
                    # Add the list item
                    block_content.append(line)
                    
                    # Check for end of list (empty line after or next line isn't a list item)
                    if i + 1 < len(lines) and not lines[i+1].strip():
                        # Empty line might signal end of list
                        if i + 2 < len(lines) and not (re.match(r'^\s*[-*+]\s', lines[i+2]) or re.match(r'^\s*\d+\.\s', lines[i+2])):
                            # Not a list item after empty line, list is ending
                            block_word_count = self._count_words(block_content)
                            
                            if current_word_count + block_word_count > self.max_chunk_size and current_word_count > 0:
                                # Start a new chunk
                                chunks.append(self._create_chunk(current_chunk))
                                
                                # Reset content tracking for overlap
                                if self.overlap_size > 0:
                                    self._update_recent_content(current_chunk, recent_content)
                                
                                # New chunk with headings and overlap
                                current_chunk = self._create_minimal_heading_prefix(heading_stack)
                                if self.overlap_size > 0 and recent_content:
                                    current_chunk.extend(self._get_overlap_content(recent_content))
                                    
                                current_word_count = self._count_words(current_chunk)
                            
                            # Add the entire list to the current chunk
                            current_chunk.extend(block_content)
                            current_chunk.append("")  # Add the empty line
                            current_word_count += block_word_count
                            
                            in_block_element = False
                            block_type = None
                            block_content = []
                            i += 1  # Skip the empty line
                            
                # Handle tables as atomic units
                elif line.strip().startswith('|') and '|' in line[1:]:
                    if not in_block_element or block_type != 'table':
                        # Process any buffered paragraph content
                        if paragraph_buffer:
                            self._process_paragraph_buffer(paragraph_buffer, current_chunk, heading_stack, chunks, recent_content)
                            paragraph_buffer = []
                        
                        # Starting a new table
                        if not in_block_element:
                            in_block_element = True
                            block_type = 'table'
                            block_content = []
                    
                    # Add the table row
                    block_content.append(line)
                    
                    # Check for end of table (next line doesn't start with |)
                    if i + 1 < len(lines) and not lines[i+1].strip().startswith('|'):
                        # Table is ending
                        block_word_count = self._count_words(block_content)
                        
                        if current_word_count + block_word_count > self.max_chunk_size and current_word_count > 0:
                            # Start a new chunk
                            chunks.append(self._create_chunk(current_chunk))
                            
                            # Reset content tracking for overlap
                            if self.overlap_size > 0:
                                self._update_recent_content(current_chunk, recent_content)
                            
                            # New chunk with headings and overlap
                            current_chunk = self._create_minimal_heading_prefix(heading_stack)
                            if self.overlap_size > 0 and recent_content:
                                current_chunk.extend(self._get_overlap_content(recent_content))
                                
                            current_word_count = self._count_words(current_chunk)
                        
                        # Add the entire table to the current chunk
                        current_chunk.extend(block_content)
                        current_word_count += block_word_count
                        
                        in_block_element = False
                        block_type = None
                        block_content = []
                    
                # Empty line
                elif not line.strip():
                    if in_block_element and block_type == 'paragraph':
                        # End of paragraph, process the buffer
                        paragraph_buffer.append(line)  # Include the blank line
                        self._process_paragraph_buffer(paragraph_buffer, current_chunk, heading_stack, chunks, recent_content)
                        paragraph_buffer = []
                        
                        in_block_element = False
                        block_type = None
                    elif not in_block_element:
                        # Just a blank line
                        current_chunk.append(line)
                    
                # Regular paragraph text
                else:
                    if not in_block_element:
                        # Starting new paragraph
                        in_block_element = True
                        block_type = 'paragraph'
                        paragraph_buffer = [line]
                    elif block_type == 'paragraph':
                        # Continue existing paragraph
                        paragraph_buffer.append(line)
                    else:
                        # Part of some other block element
                        current_chunk.append(line)
                        current_word_count += line_word_count
                
                i += 1
            
            # Process any remaining buffered paragraph
            if paragraph_buffer:
                self._process_paragraph_buffer(paragraph_buffer, current_chunk, heading_stack, chunks, recent_content)
            
            # Process any remaining block content
            if block_content:
                block_word_count = self._count_words(block_content)
                
                if current_word_count + block_word_count > self.max_chunk_size and current_word_count > 0:
                    chunks.append(self._create_chunk(current_chunk))
                    
                    # Reset content tracking for overlap
                    if self.overlap_size > 0:
                        self._update_recent_content(current_chunk, recent_content)
                    
                    # New chunk with headings and overlap
                    current_chunk = self._create_minimal_heading_prefix(heading_stack)
                    if self.overlap_size > 0 and recent_content:
                        current_chunk.extend(self._get_overlap_content(recent_content))
                    
                    current_chunk.extend(block_content)
                else:
                    current_chunk.extend(block_content)
            
            # Add the final chunk
            if current_chunk:
                chunks.append(self._create_chunk(current_chunk))
            
            # Calculate statistics
            stats["total_chunks"] = len(chunks)
            stats["avg_chunk_size"] = sum(len(chunk.split()) for chunk in chunks) / len(chunks) if chunks else 0
            stats["word_count"] = sum(len(re.findall(r'\S+', chunk)) for chunk in chunks)
            stats["breaking_points"] = [i for i, line in enumerate(lines) if line.strip() and not re.match(r'^#{1,6}\s+', line)]
            
            return (chunks, stats) if debug else chunks
        except Exception as e:
            # Log the error and return gracefully
            print(f"Error splitting markdown: {e}")
            return [] if not debug else ([], stats)
    
    def _process_paragraph_buffer(self, paragraph_buffer, current_chunk, heading_stack, chunks, recent_content):
        """Process a paragraph buffer, either adding it to the current chunk or creating a new chunk."""
        buffer_word_count = self._count_words(paragraph_buffer)
        current_word_count = self._count_words(current_chunk)
        
        # If paragraph would exceed chunk size, we may need to split or create a new chunk
        if current_word_count + buffer_word_count > self.max_chunk_size:
            if current_word_count > 0:
                # Finish current chunk and start a new one
                chunks.append(self._create_chunk(current_chunk))
                
                # Reset content tracking for overlap
                if self.overlap_size > 0:
                    self._update_recent_content(current_chunk, recent_content)
                
                # New chunk with headings and overlap
                current_chunk.clear()
                current_chunk.extend(self._create_minimal_heading_prefix(heading_stack))
                if self.overlap_size > 0 and recent_content:
                    current_chunk.extend(self._get_overlap_content(recent_content))
                
                # Now decide if paragraph fits in new chunk
                if buffer_word_count <= self.max_chunk_size:
                    # Add entire paragraph to new chunk
                    current_chunk.extend(paragraph_buffer)
                else:
                    # Handle large paragraph: keep it together if possible,
                    # or make it its own chunk
                    new_chunk_lines = self._create_minimal_heading_prefix(heading_stack)
                    if self.overlap_size > 0 and recent_content:
                        new_chunk_lines.extend(self._get_overlap_content(recent_content))
                    new_chunk_lines.extend(paragraph_buffer)
                    
                    chunks.append(self._create_chunk(new_chunk_lines))
                    
                    # Update recent content again after this large paragraph
                    if self.overlap_size > 0:
                        self._update_recent_content(paragraph_buffer, recent_content)
                    
                    # Reset current chunk
                    current_chunk.clear()
                    current_chunk.extend(self._create_minimal_heading_prefix(heading_stack))
            else:
                # Current chunk is empty, just add the paragraph as its own chunk with headings
                new_chunk_lines = self._create_minimal_heading_prefix(heading_stack)
                if self.overlap_size > 0 and recent_content:
                    new_chunk_lines.extend(self._get_overlap_content(recent_content))
                new_chunk_lines.extend(paragraph_buffer)
                
                chunks.append(self._create_chunk(new_chunk_lines))
                
                # Update recent content
                if self.overlap_size > 0:
                    self._update_recent_content(paragraph_buffer, recent_content)
        else:
            # Paragraph fits in current chunk
            current_chunk.extend(paragraph_buffer)
    
    def _update_recent_content(self, content_lines, recent_content):
        """
        Update the recent content tracking for overlap.
        
        Args:
            content_lines (list): The lines of content to add to recent content
            recent_content (list): The list tracking recent content
        """
        # Clear out old content if we're not dealing with a list
        if not isinstance(content_lines, list):
            content_lines = content_lines.split('\n')
        
        # Filter out headings and empty lines for better overlap context
        filtered_lines = []
        for line in content_lines:
            # Skip headings and blank lines
            if not line.strip() or re.match(r'^#{1,6}\s+', line):
                continue
            filtered_lines.append(line)
        
        # Add filtered content to recent tracking
        recent_content.clear()
        recent_content.extend(filtered_lines)
    
    def _get_overlap_content(self, recent_content):
        """
        Get content for overlap from recent content.
        
        Args:
            recent_content (list): Recent content from previous chunk
            
        Returns:
            list: Lines to use for overlap
        """
        if not recent_content:
            return []
        
        overlap_lines = []
        word_count = 0
        
        # Work backwards to prioritize the most recent content
        for line in reversed(recent_content):
            line_word_count = len(re.findall(r'\S+', line))
            
            # Stop if we've reached our overlap size
            if word_count + line_word_count > self.overlap_size:
                # If this is the first line and it's too long, take part of it
                if word_count == 0 and line_word_count > self.overlap_size:
                    words = line.split()
                    partial_line = ' '.join(words[:self.overlap_size])
                    overlap_lines.insert(0, partial_line)
                break
            
            # Add the line
            overlap_lines.insert(0, line)
            word_count += line_word_count
            
            if word_count >= self.overlap_size:
                break
        
        return overlap_lines
    
    def _create_minimal_heading_prefix(self, heading_stack):
        """
        Create minimal but sufficient heading context for a chunk.
        For RAG, we only include the most relevant headings up to a reasonable limit.
        
        Args:
            heading_stack (list): List of (level, text) tuples representing heading hierarchy
            
        Returns:
            list: Lines representing essential heading structure
        """
        # For RAG, we prioritize the most specific (deepest) headings
        # and only include higher-level headings if they're reasonably short
        lines = []
        
        # Get the most specific heading (last in stack)
        if not heading_stack:
            return lines
            
        # Include top-level heading for document context
        if len(heading_stack) > 0:
            level, text = heading_stack[0]
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        
        # Always include the most specific/deepest heading
        deepest_heading = heading_stack[-1]
        if len(heading_stack) > 1:  # If we have more than just the top-level heading
            level, text = deepest_heading
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        
        return lines
    
    def _count_words(self, lines):
        """Count the number of words in a list of lines."""
        if not lines:
            return 0
        return sum(len(re.findall(r'\S+', line)) for line in lines)
    
    def _create_chunk(self, lines):
        """Join lines and create a clean chunk string for RAG."""
        # Compress excessively long URLs if they appear in the text
        compressed_lines = []
        for line in lines:
            # Compress URLs to maximum of 60 chars
            line = re.sub(r'(https?://[^\s]{60,})[^\s]*', r'\1...', line)
            compressed_lines.append(line)
        
        text = '\n'.join(compressed_lines)
        
        # Remove redundant list markers and simplify bullet hierarchies
        text = self._normalize_lists(text)
        
        # Apply other normalizations to replace repeated non-alphanumeric characters
        normalized_text = self._normalize_repeated_chars(text)
        
        # Normalize code blocks - truncate extremely long code blocks
        normalized_text = self._normalize_code_blocks(normalized_text)
        
        return normalized_text
    
    def _normalize_repeated_chars(self, text):
        """
        Replace sequences of repeated non-alphanumeric characters with a single dash.
        
        Args:
            text (str): The text to normalize
            
        Returns:
            str: Normalized text with repeated special characters replaced by a dash
        """
        # This regex finds sequences of non-alphanumeric characters that repeat
        # We exclude whitespace from being replaced and certain markdown-significant chars like * # > -
        pattern = r'([^\w\s#*>\-\.\(\)\\\/\[\]\{\}])\1+'
        
        # Replace with a single dash
        normalized = re.sub(pattern, '-', text)
        
        # Additional normalization for horizontal rules (--- or ___ or ***)
        normalized = re.sub(r'[-_*]{3,}', '---', normalized)
        
        # Normalize multiple consecutive blank lines to a maximum of two
        normalized = re.sub(r'\n{3,}', '\n\n', normalized)
        
        return normalized
    
    def _normalize_lists(self, text):
        """
        Normalize markdown lists to remove redundancy while preserving structure.
        
        Args:
            text (str): The text containing markdown lists
            
        Returns:
            str: Text with normalized list formatting
        """
        lines = text.split('\n')
        result_lines = []
        consecutive_similar_items = 0
        last_list_prefix = None
        
        for line in lines:
            # Check if this is a list item line
            list_match = re.match(r'^(\s*(?:[-*+]|\d+\.)\s+)(.+)$', line)
            
            if list_match:
                prefix, content = list_match.groups()
                
                # If we have many similar list items with same prefix, start compressing
                if prefix == last_list_prefix:
                    consecutive_similar_items += 1
                    # If we've seen more than 5 consecutive items with same prefix,
                    # start compressing unless it's the first or last in the sequence
                    if consecutive_similar_items > 5:
                        if consecutive_similar_items == 6:
                            # Add an indicator that items are being compressed
                            result_lines.append(f"{prefix}...")
                        # Skip this item
                        continue
                else:
                    # Reset counter for new list type
                    consecutive_similar_items = 1
                    last_list_prefix = prefix
                
                result_lines.append(line)
            else:
                # Not a list item, reset tracking
                consecutive_similar_items = 0
                last_list_prefix = None
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    def _normalize_code_blocks(self, text):
        """
        Normalize code blocks - truncate extremely long ones.
        
        Args:
            text (str): The text containing markdown code blocks
            
        Returns:
            str: Text with normalized code blocks
        """
        # Define max lines to keep in a code block
        MAX_CODE_BLOCK_LINES = 20
        
        # Process the text to find and potentially truncate code blocks
        lines = text.split('\n')
        result_lines = []
        in_code_block = False
        code_block_lines = []
        code_block_marker = None
        
        for line in lines:
            code_start_match = re.match(r'^```(.*)$', line)
            
            if code_start_match and not in_code_block:
                # Start of a code block
                in_code_block = True
                code_block_marker = line
                code_block_lines = []
            elif line.strip() == '```' and in_code_block:
                # End of a code block
                in_code_block = False
                
                # If code block is too long, truncate it
                if len(code_block_lines) > MAX_CODE_BLOCK_LINES:
                    # Keep first and last few lines
                    keep_first = MAX_CODE_BLOCK_LINES // 2
                    keep_last = MAX_CODE_BLOCK_LINES - keep_first - 1
                    
                    truncated_block = (
                        code_block_lines[:keep_first] + 
                        [f"... [truncated {len(code_block_lines) - keep_first - keep_last} lines] ..."] + 
                        code_block_lines[-keep_last:]
                    )
                    
                    # Add truncated block to result
                    result_lines.append(code_block_marker)
                    result_lines.extend(truncated_block)
                    result_lines.append('```')
                else:
                    # Add full block to result
                    result_lines.append(code_block_marker)
                    result_lines.extend(code_block_lines)
                    result_lines.append('```')
            elif in_code_block:
                # Inside a code block
                code_block_lines.append(line)
            else:
                # Regular content
                result_lines.append(line)
        
        # Handle unclosed code block
        if in_code_block:
            result_lines.append(code_block_marker)
            
            # Apply truncation if needed
            if len(code_block_lines) > MAX_CODE_BLOCK_LINES:
                keep_first = MAX_CODE_BLOCK_LINES // 2
                keep_last = MAX_CODE_BLOCK_LINES - keep_first - 1
                
                truncated_block = (
                    code_block_lines[:keep_first] + 
                    [f"... [truncated {len(code_block_lines) - keep_first - keep_last} lines] ..."] + 
                    code_block_lines[-keep_last:]
                )
                
                result_lines.extend(truncated_block)
            else:
                result_lines.extend(code_block_lines)
                
            result_lines.append('```')
        
        return '\n'.join(result_lines)

    def split_markdown_file(self, file_path, debug=False):
        """
        Process a markdown file and split it into chunks.
        
        Args:
            file_path (str): Path to the markdown file
            debug (bool): Whether to include debug information
            
        Returns:
            list or tuple: List of chunks or tuple of (chunks, stats)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return self.split_markdown(content, debug=debug)
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")
            return [] if not debug else ([], {"error": str(e)})
