from flask import Flask, request, jsonify
import requests
import os
import tempfile

app = Flask(__name__)

# OpenAI API credentials
API_KEY = os.getenv("OPENAI_API_KEY")
GPT_API_URL = "https://api.openai.com/v1/chat/completions"
WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"

if not API_KEY:
    raise ValueError("Missing OpenAI API key. Set OPENAI_API_KEY as an environment variable.")

@app.route('/proxy', methods=['POST'])
def proxy():
    """ Main route that correctly handles both text generation and speech-to-text requests. """
    try:
        # ✅ If request contains an audio file, send it to Whisper
        if "file" in request.files:
            return handle_speech_to_text(request.files["file"])

        # ✅ If request contains text, send it to GPT
        if request.is_json:
            data = request.json
            if "user_input" in data:
                return handle_text_generation(data["user_input"])

        return jsonify({"error": "Invalid request format"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

def handle_speech_to_text(audio_file):
    """Handles speech-to-text transcription using OpenAI's Whisper API."""
    try:
        file_name = audio_file.filename
        temp_dir = tempfile.gettempdir()  # Get OS-specific temp directory
        temp_path = os.path.join(temp_dir, file_name)

        # Save the file for processing
        audio_file.save(temp_path)
        print(f"File saved at: {temp_path}")

        # Send the file to OpenAI Whisper API
        with open(temp_path, "rb") as f:
            files = {"file": (file_name, f, "audio/wav")}
            headers = {"Authorization": f"Bearer {API_KEY}"}
            data = {"model": "whisper-1"}

            response = requests.post(WHISPER_API_URL, headers=headers, files=files, data=data)

        # Remove temporary file after processing
        os.remove(temp_path)

        # Log Whisper API response
        print("Whisper API Response:", response.text)

        if response.status_code == 200:
            result = response.json()
            
            #  Force UTF-8 encoding in the proxy response
            transcribed_text = result.get("text", "No text found")
            transcribed_text = transcribed_text.encode("utf-8").decode("utf-8")

            return jsonify({"text": transcribed_text})  #  Always return UTF-8 JSON

        else:
            print("OpenAI Whisper API error:", response.text)
            return jsonify({"error": response.text}), response.status_code

    except Exception as e:
        print("Exception occurred:", str(e))  # Log error
        return jsonify({"error": str(e)}), 500

def handle_text_generation(user_input):
    """Handles text generation using OpenAI's GPT model."""
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_input},
            ],
        }

        response = requests.post(GPT_API_URL, headers=headers, json=data)

        if response.status_code != 200:
            print("OpenAI GPT API error:", response.text)
            return jsonify({
                "error": f"OpenAI GPT request failed with status {response.status_code}",
                "details": response.text,
            }), response.status_code

        return jsonify(response.json())

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)