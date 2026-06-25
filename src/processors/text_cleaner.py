import re
from typing import List

class TextCleaner:
    @staticmethod
    def clean(text: str) -> str:
        if not text:
            return ""
            
        # 1. Remove control characters
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        
        # 2. Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 3. Fix common PDF extraction issues (e.g., hyphenation at line end)
        text = re.sub(r'-\s+', '', text)
        
        return text

    @staticmethod
    def clean_chunk(text: str) -> str:
        # Additional cleaning for chunks if needed
        return TextCleaner.clean(text)
