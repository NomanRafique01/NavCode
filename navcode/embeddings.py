"""Semantic embeddings engine for navcode.

Wraps the quantised all-MiniLM-L6-v2 ONNX model to produce 384-dimensional
float32 sentence embeddings suitable for cosine-similarity search.

The model is loaded from ``~/.navcode/models/model_quantized.onnx`` (placed
there by :func:`navcode._bootstrap.ensure_model`).  The HuggingFace fast
tokenizer is loaded from the same directory.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from loguru import logger

_MODELS_DIR: Path = Path.home() / ".navcode" / "models"
_MODEL_PATH: Path = _MODELS_DIR / "model_quantized.onnx"
_TOKENIZER_PATH: Path = _MODELS_DIR / "tokenizer.json"

_BATCH_SIZE = 32
_EMBEDDING_DIM = 384


class EmbeddingsEngine:
    """ONNX-backed sentence embedding engine.

    Loads the model once on construction and exposes :meth:`embed`,
    :meth:`embed_batch`, :meth:`similarity`, and :meth:`top_k`.

    Example::

        engine = EmbeddingsEngine()
        vec = engine.embed("def parse(text: str) -> list")
        similar = engine.top_k(vec, corpus_matrix)
    """

    def __init__(self) -> None:
        """Load ONNX model and tokenizer from ``~/.navcode/models/``."""
        if not _MODEL_PATH.exists():
            raise FileNotFoundError(
                f"ONNX model not found at {_MODEL_PATH}.\n"
                "Re-run: pip install navcode  (or: navcode init)  to download it."
            )
        if not _TOKENIZER_PATH.exists():
            raise FileNotFoundError(
                f"Tokenizer not found at {_TOKENIZER_PATH}.\n"
                "Re-run: pip install navcode  (or: navcode init)  to download it."
            )

        try:
            import onnxruntime as ort  # local import — optional heavy dep
        except ImportError as exc:
            raise ImportError(
                "onnxruntime is required for semantic search. "
                "Install it with: pip install onnxruntime"
            ) from exc

        try:
            from tokenizers import Tokenizer  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "tokenizers is required for semantic search. "
                "Install it with: pip install tokenizers"
            ) from exc

        t0 = time.perf_counter()

        self._session = ort.InferenceSession(
            str(_MODEL_PATH),
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer: "Tokenizer" = Tokenizer.from_file(str(_TOKENIZER_PATH))
        self._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self._tokenizer.enable_truncation(max_length=256)

        elapsed = time.perf_counter() - t0
        logger.info("EmbeddingsEngine loaded in {:.3f}s (model={})", elapsed, _MODEL_PATH.name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def embed(self, text: str) -> np.ndarray:
        """Embed a single *text* string.

        Args:
            text: Input text to embed.

        Returns:
            Float32 numpy array of shape ``(384,)``.
        """
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed a list of *texts* efficiently.

        Processes at most :data:`_BATCH_SIZE` texts per ONNX call and
        concatenates the results.

        Args:
            texts: Input strings.

        Returns:
            Float32 numpy array of shape ``(N, 384)``.
        """
        results: list[np.ndarray] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            encodings = self._tokenizer.encode_batch(batch)

            input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )
            # outputs[0] → token embeddings: (batch, seq_len, 384)
            token_embeddings = outputs[0]
            pooled = self._mean_pool(token_embeddings, attention_mask)
            results.append(self._l2_normalize(pooled))

        return np.vstack(results).astype(np.float32)

    @staticmethod
    def similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two L2-normalised vectors.

        Args:
            a: First embedding vector.
            b: Second embedding vector.

        Returns:
            Float in ``[-1.0, 1.0]``.
        """
        return float(np.dot(a, b))

    @staticmethod
    def top_k(
        query_vec: np.ndarray,
        corpus: np.ndarray,
        k: int = 10,
    ) -> list[tuple[int, float]]:
        """Return the indices and scores of the *k* most similar corpus rows.

        Args:
            query_vec: Shape ``(384,)`` query embedding.
            corpus: Shape ``(N, 384)`` embedding matrix.
            k: Number of results.

        Returns:
            List of ``(index, score)`` sorted by score descending.
        """
        scores = corpus @ query_vec  # (N,)
        k = min(k, len(scores))
        top_indices = np.argpartition(scores, -k)[-k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]
        return [(int(idx), float(scores[idx])) for idx in top_indices]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
        """Masked mean-pool over the sequence dimension."""
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)  # (B, S, 1)
        summed = (token_embeddings * mask).sum(axis=1)              # (B, 384)
        counts = mask.sum(axis=1).clip(min=1e-9)                    # (B, 1)
        return summed / counts                                        # (B, 384)

    @staticmethod
    def _l2_normalize(x: np.ndarray) -> np.ndarray:
        """Row-wise L2 normalisation."""
        norms = np.linalg.norm(x, axis=1, keepdims=True).clip(min=1e-12)
        return x / norms
