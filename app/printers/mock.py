from .base import PrintRequest, PrinterAdapter


class MockAdapter(PrinterAdapter):
    """Adaptador sin hardware, para desarrollo y tests."""

    def __init__(self):
        self.submitted: list[PrintRequest] = []

    def submit(self, request: PrintRequest) -> str:
        self.submitted.append(request)
        return f"mock-{len(self.submitted)}"

    def status(self) -> str:
        return "ready"
