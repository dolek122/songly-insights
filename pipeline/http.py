"""HTTP helpers shared by the MusicBrainz and ListenBrainz clients."""

import time
from collections.abc import Callable

import httpx

USER_AGENT = "songly-insights/0.1"


def make_user_agent(contact: str | None) -> str:
    """Both APIs ask clients to say who they are and how to reach the author."""
    return f"{USER_AGENT} ( {contact} )" if contact else USER_AGENT


class RateLimiter:
    """Makes sure at least `min_interval_s` seconds pass between two requests.

    `sleep` and `clock` can be replaced in tests, so tests do not really wait.
    """

    def __init__(
        self,
        min_interval_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            wait = self.min_interval_s - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_request_at = now


def send_json(http: httpx.Client, limiter: RateLimiter, request: httpx.Request) -> dict:
    limiter.wait()
    response = http.send(request)
    # 503 / 429 mean "too busy / too many requests". We raise; the Prefect task retries.
    response.raise_for_status()
    return response.json()
