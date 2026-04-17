import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get("GOOGLE_AI_API_KEY", "")

import google.generativeai as genai
genai.configure(api_key=api_key)

for model_name in ["models/gemini-2.0-flash-lite", "models/gemini-flash-lite-latest", "models/gemini-2.5-flash"]:
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content("Say hello in one word.")
        print(f"SUCCESS with {model_name}: {response.text.strip()}")
        break
    except Exception as e:
        print(f"FAIL {model_name}: {type(e).__name__}: {str(e)[:150]}")
