import logging
from collections.abc import AsyncIterator
from huggingface_hub import AsyncInferenceClient
from huggingface_hub.errors import HfHubHTTPError
from backend.services.providers.base import (ProviderError, ProviderNotConfiguredError)

log = logging.getLogger(__name__)

def _format_chat_prompt(messages: list[dict]) -> str:
    prompt = ""
    system_content = ""
    
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
            
        if role == "system":
            system_content = content
        elif role == "user":
            if system_content:
                prompt += f"<s>[INST] <<SYS>>\n{system_content}\n<</SYS>>\n\n{content} [/INST]"
                system_content = ""
            else:
                prompt += f"<s>[INST] {content} [/INST]"
        elif role == "assistant":
            prompt += f" {content} </s>"
            
    return prompt.strip()

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
    client = AsyncInferenceClient(token=hf_token)
    
    try:
        try:
            res = await client.chat_completion(
                model=model_id,
                messages=messages,
                max_tokens=max_new_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in res:
                if not chunk.choices:
                    continue
                    
                token = chunk.choices[0].delta.content
                if token:
                    yield token
            return 
            
        except (HfHubHTTPError, StopIteration) as exc:
            err_body = str(exc).lower()
            
            if "403" in err_body or "gated" in err_body or "access denied" in err_body:
                raise ProviderError(
                    f"Access denied for model '{model_id}'.\n"
                    "This model is 'Gated' and requires you to accept its license on HuggingFace first.\n"
                    f"Visit: https://huggingface.co/{model_id} and click 'Expand to review' / 'Agree'."
                ) from exc

            is_modern_instruct = any(name in model_id.lower() for name in ["llama-3", "mistral-7b", "gemma", "phi-3", "zephyr"])
            is_chat_unsupported = any(term in err_body for term in ["model_not_supported", "not a chat model", "chat_completion not supported"])
            
            if is_chat_unsupported and not is_modern_instruct:
                log.info("Model %s does not support Chat API, falling back to text-generation", model_id)
                prompt = _format_chat_prompt(messages)
                res = await client.text_generation(
                    model=model_id,
                    prompt=prompt,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    stream=True,
                )
                async for token in res:
                    yield token
            else:
                raise

    except Exception as exc:
        err = str(exc)
        if not isinstance(exc, StopIteration):
            log.error("HuggingFace stream error [model=%s]: %s", model_id, err, exc_info=True)
        
        if "403" in err or "gated" in err.lower() or "access denied" in err.lower():
            raise ProviderError(
                f"Access denied for model '{model_id}'.\n"
                "This model is 'Gated' and requires you to accept its license on HuggingFace first.\n"
                f"Visit: https://huggingface.co/{model_id}"
            ) from exc

        if isinstance(exc, StopIteration) or "StopIteration" in err or "no provider" in err.lower():
            raise ProviderError(
                f"Model '{model_id}' is currently unavailable for free serverless inference.\n"
                "This usually means the model has no active free providers at the moment.\n"
                "Try using 'Llama 3.1 8B' or 'Zephyr 7B Beta'."
            ) from exc

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

        if "429" in err or "rate limit" in err.lower():
            raise ProviderError(
                "HuggingFace rate limit reached.\n"
                "Try again later or use a different model."
            ) from exc

        if "503" in err or "loading" in err.lower():
            raise ProviderError(
                f"Model '{model_id}' is warming up (cold start).\n"
                "Wait 20-30 seconds and try again."
            ) from exc

        raise ProviderError(f"Unexpected error from HuggingFace: {err}") from exc
