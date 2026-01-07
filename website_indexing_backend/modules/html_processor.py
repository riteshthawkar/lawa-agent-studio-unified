"""
HTML processing module for cleaning and converting HTML to Markdown.
Handles HTML cleaning, conversion, and file management.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import json
import logging

from markitdown import MarkItDown

from .config import ProcessingConfig

logger = logging.getLogger(__name__)


class HTMLProcessor:
    """Handles HTML cleaning and conversion to Markdown."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.md_converter = MarkItDown()

    def clean_html_file(self, html_file_path: str, output_path: str) -> bool:
        """Clean a single HTML file."""
        try:
            # For now, we'll use a simple approach - copy the file
            # In a real implementation, you'd use BeautifulSoup or similar
            # to remove ads, navigation, etc.
            shutil.copy2(html_file_path, output_path)
            return True
        except Exception as e:
            logger.error(f"Error cleaning HTML file {html_file_path}: {e}")
            return False

    def convert_html_to_markdown(self, html_content: str, output_path: str) -> bool:
        """Convert HTML content to Markdown."""
        try:
            # Write HTML to temporary file for MarkItDown
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as tmp:
                tmp.write(html_content)
                temp_html_path = tmp.name

            try:
                result = self.md_converter.convert(temp_html_path)
                markdown_content = result.text_content

                # Ensure output directory exists
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as md_file:
                    md_file.write(markdown_content)
                
                return True
            finally:
                # Clean up temp file
                if os.path.exists(temp_html_path):
                    os.unlink(temp_html_path)
                    
        except Exception as e:
            logger.error(f"Error converting HTML to Markdown: {e}")
            return False

    def process_html_files(self, input_dir: str, output_dir: str, clean_dir: str = None) -> Dict[str, Any]:
        """Process all HTML files in a directory."""
        logger.info(f"Processing HTML files from {input_dir} to {output_dir}")
        
        # Ensure output directories exist
        os.makedirs(output_dir, exist_ok=True)
        if clean_dir:
            os.makedirs(clean_dir, exist_ok=True)

        # Find all HTML files
        html_files = []
        for root, dirs, files in os.walk(input_dir):
            for file in files:
                if file.lower().endswith(('.html', '.htm')):
                    html_files.append(os.path.join(root, file))

        logger.info(f"Found {len(html_files)} HTML files to process")

        # Process files with threading
        mapping = []
        lock = Lock()
        processed_count = 0

        def process_single_file(html_file_path: str):
            nonlocal processed_count
            try:
                # Get relative path
                rel_path = os.path.relpath(html_file_path, input_dir)
                base_name = os.path.splitext(rel_path)[0]
                
                # Output paths
                clean_path = None
                if clean_dir:
                    clean_path = os.path.join(clean_dir, rel_path)
                    os.makedirs(os.path.dirname(clean_path), exist_ok=True)
                
                md_path = os.path.join(output_dir, base_name + '.md')
                os.makedirs(os.path.dirname(md_path), exist_ok=True)

                # Read HTML content
                with open(html_file_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                # Clean HTML if requested
                if clean_path:
                    if not self.clean_html_file(html_file_path, clean_path):
                        return False

                # Convert to Markdown
                if not self.convert_html_to_markdown(html_content, md_path):
                    return False

                # Update mapping
                with lock:
                    mapping.append({
                        "html_file": str(Path(html_file_path).resolve()),
                        "markdown_file": str(Path(md_path).resolve())
                    })
                    processed_count += 1

                logger.info(f"Processed: {html_file_path} -> {md_path}")
                return True

            except Exception as e:
                logger.error(f"Error processing {html_file_path}: {e}")
                return False

        # Process files in parallel
        with ThreadPoolExecutor(max_workers=self.config.html_workers) as executor:
            futures = [executor.submit(process_single_file, html_file) for html_file in html_files]
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Error in HTML processing: {e}")

        logger.info(f"Successfully processed {processed_count}/{len(html_files)} HTML files")
        
        return {
            "total_files": len(html_files),
            "processed_files": processed_count,
            "mapping": mapping
        }

    def clean_html_directory(self, input_dir: str, output_dir: str) -> Dict[str, Any]:
        """Clean all HTML files in a directory."""
        logger.info(f"Cleaning HTML files from {input_dir} to {output_dir}")
        
        os.makedirs(output_dir, exist_ok=True)
        
        # Mirror directory structure and clean files
        cleaned_count = 0
        for root, dirs, files in os.walk(input_dir):
            for file in files:
                if file.lower().endswith(('.html', '.htm')):
                    src_path = os.path.join(root, file)
                    rel_path = os.path.relpath(src_path, input_dir)
                    dst_path = os.path.join(output_dir, rel_path)
                    
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    
                    if self.clean_html_file(src_path, dst_path):
                        cleaned_count += 1

        logger.info(f"Cleaned {cleaned_count} HTML files")
        
        return {
            "cleaned_files": cleaned_count
        }
