import os
from app.ai_service import ask_ai, GEMINI_API_KEY, GEMINI_MODEL, legacy_genai, modern_genai, _model, _modern_client

print(f"DEBUG: GEMINI_API_KEY present: {bool(GEMINI_API_KEY)}")
print(f"DEBUG: GEMINI_MODEL: {GEMINI_MODEL}")
print(f"DEBUG: legacy_genai: {legacy_genai is not None}")
print(f"DEBUG: modern_genai: {modern_genai is not None}")
print(f"DEBUG: _model initialized: {_model is not None}")
print(f"DEBUG: _modern_client initialized: {_modern_client is not None}")

msg = "Hello test"
print(f"\nCalling ask_ai('{msg}')...")
try:
    resp = ask_ai(msg)
    print(f"Response: {resp}")
except Exception as e:
    print(f"Error in ask_ai: {e}")
