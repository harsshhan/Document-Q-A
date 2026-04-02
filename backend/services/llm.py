import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://router.huggingface.co/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {os.getenv('HF_API_KEY')}",
    "Content-Type": "application/json"
}

def generate_answer(context, query):
    
    prompt = f"""
    Answer the question using the context below.

    Context:
    {context}

    Question:
    {query}
    """

    payload = {
        "model": "meta-llama/Llama-3.1-8B-Instruct",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 150
    }

    try:
        response = requests.post(API_URL, headers=headers, json=payload)

        if response.status_code != 200:
            return f"LLM Error: {response.text}"

        data = response.json()

        return data["choices"][0]["message"]["content"]

    except Exception as e:
        return f"Error: {str(e)}"