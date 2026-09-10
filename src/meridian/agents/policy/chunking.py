import re
from typing import List, cast

from transformers import AutoTokenizer

TARGET_MIN = 300
TARGET_MAX = 400
OVERLAP_MIN = 45
OVERLAP_MAX = 80
BGE_MODEL_MAX = 512
MERIDIAN_SAFETY_CEILING = 480

tokenizer = AutoTokenizer.from_pretrained(
    "BAAI/bge-small-en-v1.5"
)


def chunk_document(text: str) -> List[str]:
    raw_blocks = re.split(r"\n\s*\n", text)

    tokenized_blocks = []
    for block in raw_blocks:
        if not block.strip():
            continue
        tokens = tokenizer.encode(block, add_special_tokens=False)
        # Force split huge blocks
        idx = 0
        while idx < len(tokens):
            tokenized_blocks.append(tokens[idx : idx + TARGET_MAX])
            idx += TARGET_MAX

    chunks = []
    current_tokens: List[int] = []

    for block_tokens in tokenized_blocks:
        if len(current_tokens) + len(block_tokens) > TARGET_MAX:
            # Cannot safely add without exceeding target max.
            # Must emit what we have.
            if current_tokens:
                chunks.append(cast(str, tokenizer.decode(current_tokens)))
                overlap_size = min(OVERLAP_MAX, int(0.2 * len(current_tokens)))
                current_tokens = (
                    current_tokens[-overlap_size:] if overlap_size > 0 else []
                )

            # If a block is exactly 480, it will go into current_tokens
            # and might exceed in next loop

        current_tokens.extend(block_tokens)

        if len(current_tokens) >= TARGET_MIN:
            chunks.append(cast(str, tokenizer.decode(current_tokens)))
            overlap_size = min(OVERLAP_MAX, int(0.2 * len(current_tokens)))
            current_tokens = current_tokens[-overlap_size:] if overlap_size > 0 else []

    if current_tokens and len(current_tokens) > OVERLAP_MAX:
        chunks.append(cast(str, tokenizer.decode(current_tokens)))
    elif current_tokens and not chunks:
        chunks.append(cast(str, tokenizer.decode(current_tokens)))

    return chunks
