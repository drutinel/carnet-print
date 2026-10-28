import threading

from app.jobs import JobService
from app.printers.base import PrinterAdapter, PrintRequest
from app.status import StatusCache


class Counting(PrinterAdapter):
    def __init__(self, release: threading.Event | None = None):
        self.calls = 0
        self.release = release
        self.value = "ready"

    def submit(self, request: PrintRequest) -> str:
        if self.release:
            self.release.wait(2)
        return "x"

    def status(self) -> str:
        self.calls += 1
        return self.value


def _cache(adapter, clock):
    adapters = {"p": adapter}
    jobs = JobService(adapters)
    return StatusCache(adapters, jobs, ttl=20, clock=clock), jobs


def test_status_is_cached_for_the_ttl():
    now = [0.0]
    adapter = Counting()
    cache, _ = _cache(adapter, lambda: now[0])
    assert [cache.get("p") for _ in range(5)] == ["ready"] * 5
    assert adapter.calls == 1
    now[0] = 21
    adapter.value = "offline"
    assert cache.get("p") == "offline" and adapter.calls == 2


def test_no_bridge_call_while_a_job_is_running_and_refresh_after_it():
    release = threading.Event()
    adapter = Counting(release)
    cache, jobs = _cache(adapter, lambda: 0.0)
    assert cache.get("p") == "ready" and adapter.calls == 1
    jobs.enqueue("p", {"front": b"x", "back": b"y"}, 1, {})
    assert cache.get("p") == "busy" and adapter.calls == 1
    adapter.value = "offline"
    release.set()
    jobs.shutdown()
    assert cache.get("p") == "offline"   # terminó un trabajo: no se usa el valor viejo
    assert adapter.calls == 2


def test_concurrent_queries_do_not_pile_up():
    gate = threading.Event()

    class Slow(Counting):
        def status(self) -> str:
            self.calls += 1
            gate.wait(2)
            return "ready"

    adapter = Slow()
    cache, _ = _cache(adapter, lambda: 0.0)
    results = []
    first = threading.Thread(target=lambda: results.append(cache.get("p")))
    first.start()
    while adapter.calls == 0:
        pass
    assert cache.get("p") == "unknown"   # otra consulta en curso y sin valor previo
    gate.set()
    first.join()
    assert results == ["ready"] and adapter.calls == 1
