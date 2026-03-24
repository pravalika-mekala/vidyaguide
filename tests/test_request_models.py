import unittest

from app.request_models import ChatRequest


class ChatRequestTests(unittest.TestCase):
    def test_from_payload_uses_message_field(self):
        payload = ChatRequest.from_payload({"message": "hello"})
        self.assertEqual(payload.message, "hello")

    def test_from_payload_defaults_to_empty_message(self):
        payload = ChatRequest.from_payload({})
        self.assertEqual(payload.message, "")


if __name__ == "__main__":
    unittest.main()
