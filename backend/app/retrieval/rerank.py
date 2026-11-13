"""Optional cross-encoder reranker (ONNX via fastembed). Off by default; enable only if the retrieval
benchmark shows a measurable gain on the dev split."""


class FastEmbedReranker:
    def __init__(self, model_name: str):
        self.name = model_name
        self._model = None

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name=self.name)
        return [float(s) for s in self._model.rerank(query, texts)]
