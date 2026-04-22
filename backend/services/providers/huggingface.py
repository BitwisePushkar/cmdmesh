import logging
from collections.abc import AsyncIterator
from backend.services.providers.base import (ProviderError, ProviderNotConfiguredError,
 to_langchain_messages,)
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

log = logging.getLogger(__name__)

async def stream_hf_response(
    *,
    hf_token: str,
    model_id: str,
    messages: list[dict],
    max_new_tokens: int = 2048,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    if not hf_token or not hf_token.strip():
        raise ProviderNotConfiguredError(
            "HuggingFace API token is required to chat.\n"
            "Get your free token at: https://huggingface.co/settings/tokens"
        )
    hf_token = hf_token.strip()
    try:
        endpoint = HuggingFaceEndpoint(
            repo_id=model_id,
            huggingfacehub_api_token=hf_token,
            task="text-generation",
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            do_sample=True,
            streaming=True,
            return_full_text=False,
        )
        chat_model = ChatHuggingFace(llm=endpoint)
        lc_messages = to_langchain_messages(messages)
        async for chunk in chat_model.astream(lc_messages):
            text = chunk.content
            if isinstance(text, str) and text:
                yield text

    except ProviderNotConfiguredError:
        raise

    except ImportError as exc:
        raise ProviderError(
            "langchain-huggingface is not installed.\n"
            "Run: uv pip install langchain-huggingface huggingface-hub"
        ) from exc

    except Exception as exc:
        err = str(exc)
        log.error("HuggingFace stream error [model=%s]: %s", model_id, err)
        
        if "401" in err or "unauthorized" in err.lower() or "invalid token" in err.lower():
            raise ProviderError(
                "Invalid HuggingFace API token. "
                "Check your token at https://huggingface.co/settings/tokens"
            ) from exc

        if "403" in err or "access" in err.lower():
            raise ProviderError(
                f"Access denied for model '{model_id}'.\n"
                "Some models require accepting a license on huggingface.co first.\n"
                f"Visit: https://huggingface.co/{model_id}"
            ) from exc

        if "404" in err or "not found" in err.lower():
            raise ProviderError(
                f"Model '{model_id}' not found on HuggingFace Hub."
            ) from exc

        if "422" in err:
            raise ProviderError(
                f"Model '{model_id}' does not support the chat completions API. "
                "Please choose an instruct model."
            ) from exc

        if "429" in err or "rate limit" in err.lower():
            raise ProviderError(
                "HuggingFace rate limit reached.\n"
                "Free tier allows ~1000 requests/day. Try again tomorrow or use a different model."
            ) from exc

        if "503" in err or "loading" in err.lower():
            raise ProviderError(
                f"Model '{model_id}' is warming up (cold start).\n"
                "Wait 20-30 seconds and try again — this only happens on the first request."
            ) from exc

        if "timeout" in err.lower():
            raise ProviderError(
                "Request timed out. The model may be overloaded. Try again in a moment."
            ) from exc

        raise ProviderError(f"Unexpected error from HuggingFace: {err}") from exc