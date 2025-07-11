# STOP PROCRASTINATION  
### BE PRODUCTIVE!  

# Window Focus Reminder  

A script to track active windows and remind users to return to their work applications.  

## Features  

- ✅ Active window tracking  
- ✅ Sound reminders for distractions  
- ✅ Voice notifications via Edge TTS  
- ✅ AI integration for personalized messages  
- ✅ Session system (focus/break)  
- ✅ Discord Rich Presence  
- ✅ Support for multiple AI providers (Llama, Google Assistant)  

## Supported AI Providers  

### 1. Llama (Local)  
To use a local Llama server:  
```json  
{  
  "ai_provider": "llama",  
  "llama_url": "http://127.0.0.1:8080/completion"  
}  
```  

### 2. Google Assistant API  
To use Google Assistant API:  
```json  
{  
  "ai_provider": "google_assistant",  
  "google_assistant_api_key": "YOUR_API_KEY",  
  "google_project_id": "YOUR_PROJECT_ID"  
}  
```  

## Installation  

1. Install dependencies:  
```bash  
pip install -r requirements.txt  
```  

2. Configure `config.json`:  
   - Choose an AI provider (`ai_provider`)  
   - Set parameters for the selected provider  
   - Specify target applications in `target_apps`  

3. Create a session file `sessions.jsonl`:  
```json  
{"name": "Focus", "focus": true, "min": 25}  
{"name": "Break", "focus": false, "min": 5}  
{"name": "Focus", "focus": true, "min": 25}  
```  

## Usage  

Run the script:  
```bash  
python main.py  
```  

## Configuration  

### Main Parameters:  
- `ai_provider`: AI provider selection (`llama` or `google_assistant`)  
- `target_apps`: List of target applications  
- `reminder_interval`: Time until reminder (seconds)  
- `punishment_interval`: Time until AI "punishment" (seconds)  
- `praise_interval`: Time for AI "praise" (seconds)  

### Llama Parameters:  
- `llama_url`: Local Llama server URL  
- `temperature`: Generation temperature  
- `n_predict`: Maximum token count  

### Google Assistant Parameters:  
- `google_assistant_api_key`: Google API key  
- `google_project_id`: Google project ID  
- `google_max_tokens`: Maximum token count  

## File Structure  

```  
workReminder/  
├── main.py              # Main script  
├── ai_client.py         # AI client module  
├── config.json          # Configuration  
├── sessions.jsonl       # Session file  
├── session_stats.json   # Session statistics  
├── requirements.txt     # Dependencies  
└── README.MD           # Documentation  
```  

## License  

MIT License  

Python script to help maintain focus on work applications.  
One timer alerts every 5 seconds to return to work,  
another uses AI to generate "punishment" messages,  
and a third prompts AI to generate "praise" messages.  

***After being abandoned by a friend with no moral support for work, I enhanced my AI interface. This solution was eventually condensed into a single Python script.***  

*Hope it helps you stay focused!*  

*JErfurt*  

[YT video (old)](https://www.youtube.com/watch?v=AqjlrRfCPb8)  

## Installation  
Use Conda or Venv to avoid system conflicts.  
For the AI backend, llama.cpp server is recommended. Check out [llama.cpp](https://github.com/ggerganov/llama.cpp) – it's very user-friendly!  

### Simplified Windows Guide  

1. Clone/unpack the repository and open the folder in CMD.  
2. Create a virtual environment:  
```  
python -m venv venv  
```  
3. Activate the environment:  
```  
venv\Scripts\activate  
```  
4. Install dependencies:  
```  
pip install -r requirements.txt  
```  
5. Download a compatible release from [llama.cpp/releases](https://github.com/ggerganov/llama.cpp/releases) (e.g., CUDA for GPU or AVX2 for CPU).  
6. Unpack llama.cpp and place it in your preferred location.  
7. Download a GGUF model from [HuggingFace](https://huggingface.co/) (e.g., llama-3B).  

### Launching the Server  

For CUDA (adjust GPU layers as needed):  
```  
llama-server.exe -m Models/YOUR_MODEL.gguf --n-gpu-layers 29 --split-mode layer --main-gpu 0 --ctx-size 4096  
```  

For CPU-only:  
```  
llama-server.exe -m Models/YOUR_MODEL.gguf --ctx-size 4096  
```  

### Running the Script  

Reactivate the virtual environment if needed:  
```  
venv\Scripts\activate  
```  

Start the main script:  
```  
python main.py  
```  

### Quick Setup Summary  
The process is straightforward. For additional details, refer to the documentation.  

--------