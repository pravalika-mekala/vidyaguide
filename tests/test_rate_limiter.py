import unittest

from app.rate_limiter import RateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_allows_until_limit_then_blocks(self):
        limiter = RateLimiter()
        self.assertEqual(limiter.allow("key", limit=2, window_seconds=60), (True, 0))
        self.assertEqual(limiter.allow("key", limit=2, window_seconds=60), (True, 0))
        allowed, retry_after = limiter.allow("key", limit=2, window_seconds=60)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry_after, 1)


if __name__ == "__main__":
    unittest.main()
