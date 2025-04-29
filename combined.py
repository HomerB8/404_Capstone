import os
import json
import requests
import tempfile
import unicodedata
import subprocess
from flask import Flask, request, jsonify

app = Flask(__name__)

# Constants
API_KEY = os.getenv("OPENAI_API_KEY")
GPT_API_URL = "https://api.openai.com/v1/chat/completions"
WHISPER_API_URL = "https://api.openai.com/v1/audio/transcriptions"
TTS_API_URL = "https://api.openai.com/v1/audio/speech"

LOCAL_MP3_PATH = "/tmp/tts_output.mp3"
PROCESSED_MP3_PATH = "/tmp/tts_output_processed.mp3"
PEPPER_IP = "10.250.8.66"
PEPPER_USER = "nao"
PEPPER_DEST_PATH = "/home/nao/tts_output.mp3"
CONVO_LOG_PATH_EN = os.path.join(os.path.expanduser("~"), "conversation_log.json")
FFMPEG_PATH = r"C:\Users\tigar\OneDrive\pic\ffmpeg-7.1.1-essentials_build\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe"

def initialize_convo_log():
    if not os.path.exists(CONVO_LOG_PATH_EN):
        with open(CONVO_LOG_PATH_EN, "w") as f:
            json.dump([], f)

@app.route("/proxy", methods=["POST"])
def proxy():
    try:
        lang = None
        if "file" in request.files:
            lang = request.form.get("language", "es")
        elif request.is_json:
            lang = request.json.get("language")
        if not lang:
            return jsonify({"error": "Language not specified"}), 400

        return spanish_handler(request) if lang == "es" else english_handler(request)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def english_handler(req):
    try:
        if "file" in req.files:
            return transcribe_audio(req.files["file"], "en")
        elif req.is_json:
            return handle_text_generation_en(req.json["user_input"])
        return jsonify({"error": "Invalid English request format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def spanish_handler(req):
    try:
        if "file" in req.files:
            return transcribe_audio(req.files["file"], "es")  # <- ✅ FIX: only return transcription
        elif req.is_json:
            user_input = req.json["user_input"]
            bypass = req.json.get("bypass_gpt", False)
            return handle_text_generation_es(user_input, bypass_gpt=bypass)
        return jsonify({"error": "Invalid Spanish request format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def transcribe_audio(audio_file, lang):
    try:
        temp_path = os.path.join(tempfile.gettempdir(), audio_file.filename)
        audio_file.save(temp_path)
        with open(temp_path, "rb") as f:
            files = {"file": (audio_file.filename, f, "audio/wav")}
            headers = {"Authorization": f"Bearer {API_KEY}"}
            data = {"model": "whisper-1", "language": lang}
            response = requests.post(WHISPER_API_URL, headers=headers, files=files, data=data, timeout=60)

        os.remove(temp_path)

        # ✅ Add debug log
        print("[DEBUG] Whisper API raw response:", response.text)

        if response.status_code == 200:
            return response.json()
        else:
            return jsonify({"error": response.text}), response.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def handle_text_generation_en(user_input):
    try:
        initialize_convo_log()
        try:
            with open(CONVO_LOG_PATH_EN, "r") as f:
                conversation_history = json.load(f)
        except json.JSONDecodeError:
            conversation_history = []

        conversation_history.append({"role": "user", "content": user_input})
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "system", "content": "You are a helpful and engaging assistant."}] + conversation_history[-5:]
        }

        response = requests.post(GPT_API_URL, headers=headers, json=data, timeout=60)
        gpt_response = response.json()["choices"][0]["message"]["content"].strip()
        conversation_history.append({"role": "assistant", "content": gpt_response})
        with open(CONVO_LOG_PATH_EN, "w") as f:
            json.dump(conversation_history, f, indent=4)

        success = save_tts_to_pepper(gpt_response, language="en")
        if not success:
            return jsonify({"error": "TTS generation failed."}), 500
        return jsonify({"response": gpt_response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def handle_text_generation_es(user_input, bypass_gpt=False):
    try:
        if bypass_gpt:
            text_to_speak = user_input
        else:
            headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
            data = {
                "model": "gpt-3.5-turbo",
                "messages": [
                    {"role": "system", "content": "Responde en español manteniendo el idioma del usuario."},
                    {"role": "user", "content": user_input}
                ]
            }

            response = requests.post(GPT_API_URL, headers=headers, json=data, timeout=60)
            text_to_speak = response.json()["choices"][0]["message"]["content"].strip()

        stripped_display_text = unicodedata.normalize("NFD", text_to_speak)
        stripped_display_text = "".join(c for c in stripped_display_text if unicodedata.category(c) != "Mn")
        stripped_display_text = stripped_display_text.replace("¿", "").replace("¡", "")

        success = save_tts_to_pepper(text_to_speak, language="es")
        if not success:
            return jsonify({"error": "TTS generation failed."}), 500
        return jsonify({"response": stripped_display_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def save_tts_to_pepper(text, language):
    print(f"[INFO] Generating TTS for: {text}")
    try:
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": "nova",
            "response_format": "mp3"
        }

        tts_response = requests.post(TTS_API_URL, headers=headers, json=payload, stream=True, timeout=60)
        if tts_response.status_code != 200:
            print(f"[ERROR] TTS API Error: {tts_response.text}")
            return False

        with open(LOCAL_MP3_PATH, "wb") as f:
            for chunk in tts_response.iter_content(chunk_size=8192):
                f.write(chunk)

        print("[INFO] TTS MP3 saved successfully.")

        if language == "es":
            print("[INFO] Boosting and slowing Spanish audio...")
            if not boost_and_slow_audio(LOCAL_MP3_PATH, PROCESSED_MP3_PATH):
                return False
            upload_path = PROCESSED_MP3_PATH
        else:
            upload_path = LOCAL_MP3_PATH

        print(f"[INFO] Uploading MP3 to Pepper at {PEPPER_DEST_PATH}")
        subprocess.run(["scp", upload_path, f"{PEPPER_USER}@{PEPPER_IP}:{PEPPER_DEST_PATH}"], check=True)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save TTS: {e}")
        return False

def boost_and_slow_audio(input_path, output_path):
    try:
        if not os.path.exists(FFMPEG_PATH):
            raise FileNotFoundError("FFmpeg binary not found.")
        temp_wav = input_path.replace(".mp3", "_temp.wav")

        subprocess.run([
            FFMPEG_PATH, "-y", "-i", input_path,
            "-filter:a", "volume=3.5,atempo=0.9",
            "-ar", "16000", temp_wav
        ], check=True)

        subprocess.run([
            FFMPEG_PATH, "-y", "-i", temp_wav,
            "-codec:a", "libmp3lame", "-q:a", "4",
            output_path
        ], check=True)

        os.remove(temp_wav)
        print("[INFO] Audio successfully processed.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to process audio: {e}")
        return False

if __name__ == "__main__":
    initialize_convo_log()
    app.run(host="0.0.0.0", port=8080)
