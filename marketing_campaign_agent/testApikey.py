import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dotenv import find_dotenv, load_dotenv


def test_gemini_api_key():
    # Load environment variables from the root .env
    load_dotenv(find_dotenv(), override=True)
    
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    
    if not api_key:
        print("[ERROR] GEMINI_API_KEY is not set or is empty in .env")
        return False
        
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 10 else "***"
    print(f"[INFO] Found GEMINI_API_KEY: {masked_key}")
    print("[INFO] Testing API key with Gemini API...")

    try:
        from google import genai
        
        client = genai.Client(api_key=api_key)
        
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
        return True
        
    except Exception as e:
        print("\n" + "="*50)
        print(f"[FAILED] Error testing GEMINI_API_KEY: {e}")
        print("="*50)
        return False


def test_youtube_api_key():
    # Load environment variables from the root .env
    load_dotenv(find_dotenv(), override=True)
    
    api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    
    if not api_key:
        print("\n" + "="*50)
        print("[ERROR] YOUTUBE_API_KEY is not set or is empty in .env")
        print("="*50)
        return False
        
    masked_key = f"{api_key[:6]}...{api_key[-4:]}" if len(api_key) > 10 else "***"
    print("\n" + "-"*50)
    print(f"[INFO] Found YOUTUBE_API_KEY: {masked_key}")
    print("[INFO] Testing API key with YouTube Data API v3...")

    try:
        encoded_query = urllib.parse.quote("marketing digital")
        url = (
            f"https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={encoded_query}&type=video&maxResults=1&key={api_key}"
        )
        
        req = urllib.request.Request(url, headers={"User-Agent": "MarketingAgents/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            items = data.get("items", [])
            sample_title = items[0]["snippet"]["title"] if items else "No items returned"
            
            print("\n" + "="*50, flush=True)
            print("[SUCCESS] YOUTUBE_API_KEY is valid and working with YouTube Data API v3!", flush=True)
            print(f"[SAMPLE VIDEO FOUND]: {sample_title}", flush=True)
            print("="*50, flush=True)
            return True

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            err_json = json.loads(error_body)
            err_msg = err_json.get("error", {}).get("message", error_body)
        except Exception:
            err_msg = error_body
            
        print("\n" + "="*50)
        print(f"[FAILED] YouTube Data API HTTP {e.code} Error: {err_msg}")
        if e.code == 401 or "API keys are not supported" in err_msg:
            print("\n[TIP] La clave configurada en YOUTUBE_API_KEY proviene de Google AI Studio (formato AQ.Ab8...).")
            print("Para la YouTube Data API v3, se requiere una API Key de Google Cloud Console (formato AIzaSy...)")
            print("con la API 'YouTube Data API v3' habilitada en la consola de Google Cloud.")
        print("="*50)
        return False
    except Exception as e:
        print("\n" + "="*50)
        print(f"[FAILED] Error testing YOUTUBE_API_KEY: {e}")
        print("="*50)
        return False



if __name__ == "__main__":
    gemini_ok = test_gemini_api_key()
    youtube_ok = test_youtube_api_key()
    
    if not (gemini_ok and youtube_ok):
        sys.exit(1)
