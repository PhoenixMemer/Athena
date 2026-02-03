import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv() # Load the .env file
API_KEY = os.getenv('AI_API_KEY') # Get the key

print(f"Testing API Key: {API_KEY}")

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

try:
    response = model.generate_content("Hello, are you operational?")
    print("SUCCESS! Response:", response.text)
except Exception as e:
    print("FAILED! Error:", e)