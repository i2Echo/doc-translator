from __future__ import annotations

from babeldoc.translator.translator import BaseTranslator
from babeldoc.utils.atomic_integer import AtomicInteger

from doc_translator.model_api import ModelApiClient, ModelCompletion
from doc_translator.settings_service import RuntimeSettings


class BabeldocModelTranslator(BaseTranslator):
    name = "model-api"

    def __init__(self, runtime: RuntimeSettings, *, lang_in: str, lang_out: str) -> None:
        super().__init__(lang_in, lang_out, ignore_cache=False)
        self.model = runtime.model_name
        self.client = ModelApiClient(
            api_format=runtime.model_api_format,
            base_url=runtime.model_base_url,
            api_key=runtime.model_api_key,
            model=runtime.model_name,
            timeout_seconds=runtime.model_timeout_seconds,
            max_connections=None,
        )
        self.add_cache_impact_parameters("api_format", runtime.model_api_format.value)
        self.add_cache_impact_parameters("model", self.model)
        self.add_cache_impact_parameters("prompt", self.prompt(""))
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()

    def close(self) -> None:
        self.client.close()

    def do_translate(self, text: str, rate_limit_params: dict | None = None) -> str:
        completion = self.client.complete(self.prompt(text))
        self._record_usage(completion)
        return completion.text

    def do_llm_translate(self, text: str | None, rate_limit_params: dict | None = None) -> str | None:
        if text is None:
            return None
        completion = self.client.complete(
            [{"role": "user", "content": text}],
            json_mode=bool(rate_limit_params and rate_limit_params.get("request_json_mode")),
        )
        self._record_usage(completion)
        return completion.text

    def prompt(self, text: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": "You are a professional, authentic machine translation engine.",
            },
            {
                "role": "user",
                "content": (
                    f";; Treat next line as plain text input and translate it into {self.lang_out}, "
                    "output translation ONLY. If translation is unnecessary (e.g. proper nouns, codes, "
                    "{{1}}, etc.), return the original text. NO explanations. NO notes. Input:\n\n"
                    f"{text}"
                ),
            },
        ]

    def _record_usage(self, completion: ModelCompletion) -> None:
        self.token_count.inc(completion.total_tokens)
        self.prompt_token_count.inc(completion.input_tokens)
        self.completion_token_count.inc(completion.output_tokens)
        self.cache_hit_prompt_token_count.inc(completion.cached_input_tokens)

    def get_formular_placeholder(self, placeholder_id: int | str) -> tuple[str, str]:
        return "{v" + str(placeholder_id) + "}", f"{{\\s*v\\s*{placeholder_id}\\s*}}"

    def get_rich_text_left_placeholder(self, placeholder_id: int | str) -> tuple[str, str]:
        return (
            f"<style id='{placeholder_id}'>",
            f"<\\s*style\\s*id\\s*=\\s*'\\s*{placeholder_id}\\s*'\\s*>",
        )

    def get_rich_text_right_placeholder(self, placeholder_id: int | str) -> tuple[str, str]:
        return "</style>", r"<\s*\/\s*style\s*>"
