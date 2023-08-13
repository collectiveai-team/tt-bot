import heapq
import asyncio

import numpy as np

from rich.progress import track
from more_itertools import flatten

from tt_bot.logger import get_logger
from tt_bot.cache import async_cache
from tt_bot.utils.json_data import group_by_key
from tt_bot.meta import (
    SearchEngine,
    TextEncoder,
    WebExtractor,
    Retrieval,
    RetrievalResponse,
)


logger = get_logger(__name__)


class WebRetrieval(Retrieval):
    def __init__(
        self,
        search_engine: SearchEngine,
        text_encoder: TextEncoder,
        extractors: dict[str, WebExtractor],
        sim_tresh: float = 0.8,
        top_k: int = 3,
    ):
        super().__init__(
            search_engine=search_engine,
            text_encoder=text_encoder,
            extractors=extractors,
            sim_tresh=sim_tresh,
            top_k=top_k,
        )

    def merge_chunk_group(self, chunk_group: list[dict]) -> dict:
        merged_group = {
            "source": chunk_group[0]["source"],
            "texts": [chunk["text"] for chunk in chunk_group],
            "relevance": len(chunk_group),
            "similarity": max(chunk["similarity"] for chunk in chunk_group),
        }

        return merged_group

    @async_cache
    async def retrieve(self, query_text: str) -> list[RetrievalResponse]:
        search_responses = self.search_engine.search(query_text)
        if not search_responses:
            return []

        async_tasks = (
            self.extractors[search_response.extract_strategy].async_extract(
                search_response
            )
            for search_response in track(
                search_responses, description="runing web extractors"
            )
        )

        text_chunks = await asyncio.gather(*async_tasks)
        text_chunks = list(flatten(text_chunks))

        texts = [tc.text for tc in text_chunks]
        chunk_embeddings = self.text_encoder.encode(texts=texts)
        logger.info(f"chunk_embeddings => {chunk_embeddings.shape}")

        question_embedding = self.text_encoder.encode([query_text])
        sims = np.inner(question_embedding, chunk_embeddings).ravel()
        sims_idx = np.nonzero(sims >= self.sim_tresh)[0]
        if not len(sims_idx):
            logger.info("no good enough answers")
            return []

        relevant_chunks = (
            text_chunk.dict() | {"similarity": sims[idx]}
            for idx, text_chunk in enumerate(text_chunks)
            if idx in sims_idx
        )

        chunk_groups = group_by_key(
            relevant_chunks,
            group_key="source",
            sort_key="source",
        )

        sim_chunks = map(self.merge_chunk_group, chunk_groups)
        # NOTE Sorting the entire list would require O(n log n) time
        # complexity, whereas using a heap for maintaining the top-k elements
        # requires approximately O(n log k) time complexity.
        sim_chunks = heapq.nlargest(
            self.top_k,
            sim_chunks,
            key=lambda x: (x["relevance"], x["similarity"]),
        )

        retrieval_responses = [RetrievalResponse(**sc) for sc in sim_chunks]
        return retrieval_responses