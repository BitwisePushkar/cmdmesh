from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

class ProviderError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)

class ProviderNotConfiguredError(ProviderError):
    pass

def to_langchain_messages(messages: list[dict]) -> list[BaseMessage]:
    result: list[BaseMessage] = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            result.append(SystemMessage(content=content))
        elif role == "assistant":
            result.append(AIMessage(content=content))
        else:
            result.append(HumanMessage(content=content))
    return result