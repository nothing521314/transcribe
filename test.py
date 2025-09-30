import google.generativeai as genai
from flask import (
    jsonify,
)


def extract_response_text(response) -> str:
        """
        Safely extract text by ONLY accessing the candidates/parts structure, 
        completely ignoring the problematic response.text accessor.
        """
        
        # Kiểm tra và log finish_reason trước
        finish_reason = getattr(getattr(response, "candidates", [None])[0], "finish_reason", None)
        if finish_reason:
            print(f"Response finish reason: {finish_reason}")
            
        if finish_reason and finish_reason.value in [2, 3]: # STOP (2) hoặc SAFETY (3)
             print(f"Gemini finished with reason {finish_reason.value}. Checking prompt_feedback...")
             
             # Kiểm tra phản hồi bị chặn
             if hasattr(response, "prompt_feedback") and hasattr(response.prompt_feedback, "block_reason"):
                print(f"Response blocked: {getattr(response.prompt_feedback.block_reason, 'name', 'N/A')}")
             return ""


        # Logic trích xuất chính: CHỈ lặp qua candidates/parts
        if hasattr(response, "candidates") and response.candidates:
            candidate = response.candidates[0]
            content = getattr(candidate, "content", None)
            
            if content and hasattr(content, "parts"):
                text_parts = []
                for part in content.parts:
                    # Dùng getattr an toàn để trích xuất text
                    text = getattr(part, "text", "") 
                    if text:
                        text_parts.append(text)
                
                if text_parts:
                    return "\n".join(text_parts)
        
        print(f"Could not extract text from Gemini response (Failed candidates/parts check). Raw: {response}")
        return ""

def test_gemini_api_key(api_key: str) -> bool:
    """
    Test a Gemini API key by making a simple request.
    Returns True if the key is valid, False otherwise.
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content("Hello")
        # Try to extract text from response
        response_text = extract_response_text(response)
        print(f"response_text: {response_text}")
        if response_text:
            return True
        return False
    except Exception as e:
        print(f"API key test failed: {e}")
        return False

if __name__ == "__main__":
    key = input("Enter Gemini API key: ").strip()
    if test_gemini_api_key(key):
        print("✅ API key is valid!")
    else:
        print("❌ API key is invalid or has issues.")

