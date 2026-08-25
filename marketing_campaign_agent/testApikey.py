import os
import sys
from dotenv import find_dotenv, load_dotenv

def test_gemini_api_key():
    # Load environment variables from the root .env
    load_dotenv(find_dotenv(), override=True)
    
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    
    if not api_key:
        print("[ERROR] GEMINI_API_KEY is not set or is empty in .env")
        sys.exit(1)
        
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 10 else "***"
    print(f"[INFO] Found GEMINI_API_KEY: {masked_key}")
    print("[INFO] Testing API key with Gemini API...")

    try:
        from google import genai
        
        client = genai.Client(api_key=api_key)
        
        # Test generation with gemini-2.5-flash or list models
        model_name = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.5-flash")
        print(f"[INFO] Sending test prompt to model '{model_name}'...", flush=True)
        
        response = client.models.generate_content(
            model=model_name,
            contents="Hello! Please reply with exactly: 'API key is valid and working!'"
        )
        
        print("\n" + "="*50, flush=True)
        print("[SUCCESS] GEMINI_API_KEY is valid and working!", flush=True)
        print(f"[MODEL RESPONSE]: {response.text.strip()}", flush=True)
        print("="*50, flush=True)
        
    except Exception as e:
        print("\n" + "="*50)
        print(f"[FAILED] Error testing GEMINI_API_KEY: {e}")
        print("="*50)
        sys.exit(1)

if __name__ == "__main__":
    test_gemini_api_key()
