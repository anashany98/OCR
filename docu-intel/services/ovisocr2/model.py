"""Single-load, bounded OvisOCR2 vLLM runtime."""

from __future__ import annotations

import concurrent.futures
import logging
import os
import threading
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger("ovisocr2.model")

PROMPT_VERSION = "ovisocr2-document-markdown-v1"
OCR_PROMPT = (
    "Extract all readable content from the image in natural human reading order and output the "
    "result as a single Markdown document. For charts or images, represent them using an HTML "
    'image tag: <img src="images/bbox_{left}_{top}_{right}_{bottom}.jpg" />, where left, top, '
    "right, bottom are bounding box coordinates scaled to [0, 1000). Format formulas as LaTeX. "
    "Format tables as HTML: <table>...</table>. Transcribe all other text as standard Markdown. "
    "Preserve the original text without translation or paraphrasing."
)


@dataclass(frozen=True)
class ModelOutput:
    markdown: str
    finish_reason: str
    output_tokens: int


class OvisOCR2Model:
    """Own one vLLM instance for the lifetime of this service process."""

    def __init__(self) -> None:
        self.model_name = os.environ.get("OVISOCR2_MODEL", "ATH-MaaS/OvisOCR2")
        self.revision = os.environ.get(
            "OVISOCR2_MODEL_REVISION", "77bfe9462d1e6f8965ee6698f08ea8ede580912c"
        )
        self.gpu_memory_utilization = float(
            os.environ.get("OVISOCR2_GPU_MEMORY_UTILIZATION", "0.50")
        )
        self.min_pixels = int(os.environ.get("OVISOCR2_MIN_PIXELS", str(448 * 448)))
        self.max_pixels = int(os.environ.get("OVISOCR2_MAX_PIXELS", str(2880 * 2880)))
        self.max_tokens = int(os.environ.get("OVISOCR2_MAX_TOKENS", "16384"))
        self.max_model_len = int(os.environ.get("OVISOCR2_MAX_MODEL_LEN", "32768"))
        self._state = "loading"
        self._detail: str | None = None
        self._model = None
        self._prompt: str | None = None
        self._lock = threading.Lock()
        self._loader: concurrent.futures.Future[None] | None = None
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ovis-load"
        )

    @property
    def state(self) -> str:
        return self._state

    @property
    def detail(self) -> str | None:
        return self._detail

    def start_loading(self) -> None:
        with self._lock:
            if self._loader is None:
                self._loader = self._executor.submit(self._load)

    def _load(self) -> None:
        try:
            # vLLM is imported only in the inference image.  The backend never
            # imports this module or gains this CUDA dependency.
            from vllm import LLM, SamplingParams  # type: ignore[import-not-found]

            if not self.revision or len(self.revision) < 12:
                raise RuntimeError(
                    "OVISOCR2_MODEL_REVISION must be an immutable commit"
                )
            llm = LLM(
                model=self.model_name,
                revision=self.revision,
                tokenizer_revision=self.revision,
                tensor_parallel_size=1,
                gpu_memory_utilization=self.gpu_memory_utilization,
                max_model_len=self.max_model_len,
                gdn_prefill_backend="triton",
            )
            prompt = llm.get_tokenizer().apply_chat_template(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image"},
                            {"type": "text", "text": OCR_PROMPT},
                        ],
                    }
                ],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            self._sampling_params_type = SamplingParams
            self._model = llm
            self._prompt = prompt
            self._state = "ready"
            logger.info(
                "ovisocr2_model_ready revision=%s prompt_version=%s",
                self.revision,
                PROMPT_VERSION,
            )
        except Exception as exc:  # noqa: BLE001 - retain diagnostic for /readyz, don't crash-loop
            self._detail = f"{type(exc).__name__}: {exc}"[:500]
            self._state = "failed"
            logger.exception("ovisocr2_model_load_failed")

    def parse(self, image: Image.Image, max_tokens: int | None = None) -> ModelOutput:
        if self._state != "ready" or self._model is None or self._prompt is None:
            raise RuntimeError(self._detail or "OvisOCR2 model is not ready")
        tokens = min(max(1, int(max_tokens or self.max_tokens)), self.max_tokens)
        params = self._sampling_params_type(max_tokens=tokens, temperature=0.0)
        outputs = self._model.generate(
            [
                {
                    "prompt": self._prompt,
                    "multi_modal_data": {"image": image},
                    "mm_processor_kwargs": {
                        "images_kwargs": {
                            "min_pixels": self.min_pixels,
                            "max_pixels": self.max_pixels,
                        }
                    },
                }
            ],
            params,
        )
        output = outputs[0].outputs[0]
        finish_reason = str(getattr(output, "finish_reason", "stop") or "stop").lower()
        if finish_reason not in {"stop", "length"}:
            finish_reason = "error"
        token_ids = getattr(output, "token_ids", None) or []
        return ModelOutput(
            markdown=str(getattr(output, "text", "") or "").strip(),
            finish_reason=finish_reason,
            output_tokens=len(token_ids),
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["ModelOutput", "OCR_PROMPT", "OvisOCR2Model", "PROMPT_VERSION"]
