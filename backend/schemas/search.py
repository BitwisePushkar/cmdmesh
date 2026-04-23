from pydantic import BaseModel, Field, HttpUrl, field_validator

class SearchQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)
    ai_question: str | None = Field(default=None, max_length=1000)
    session_id: str | None = Field(default=None) 

    @field_validator("query")
    @classmethod
    def query_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Search query cannot be blank.")
        return v.strip()

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    position: int

class SearchQueryResponse(BaseModel):
    query: str
    results: list[SearchResult]
    ai_answer: str | None = None   
    total_found: int

class URLContextRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    ai_question: str | None = Field(default=None, max_length=1000)
    session_id: str | None = Field(default=None)
    max_chars: int = Field(
        default=8000, ge=500, le=20000,
        description="Max extracted characters to inject as context"
    )

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        if "." not in v.split("//")[-1]:
            raise ValueError("URL does not look valid. Include the domain, e.g. https://example.com")
        return v

class URLContextResponse(BaseModel):
    url: str
    title: str | None
    extracted_text: str          
    char_count: int
    ai_answer: str | None = None  
    error: str | None = None    

class ContextInjectedResponse(BaseModel):
    session_id: str
    message: str
    context_chars: int