class OpenAIHttpError(RuntimeError):
    def __init__(self, status_code: int, response_body: str):
        super().__init__(f"HTTP {status_code}: {response_body}")
        self.status_code = status_code
        self.response_body = response_body


class OpenAITransportError(RuntimeError):
    pass
