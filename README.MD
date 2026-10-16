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
- ✅ Support for multiple AI providers (llama.cpp, any OpenAI-compatible API, Gemini) with fallback chain
- ✅ Context-aware AI: time of day, current session, distraction statistics
- ✅ Dialogue memory: the assistant remembers recent replies and does not repeat facts
- ✅ Async requests with timeouts and retries, TTS-safe output cleanup, offline fallback phrases

## Supported AI Providers

### 1. llama.cpp (`/completion`, raw prompt)
```json
{
  "ai_provider": "llama",
  "llama_url": "http://127.0.0.1:8080/completion"
}
```

### 2. OpenAI-compatible Chat API (recommended for local models)
Works with llama.cpp (`/v1`), Ollama, LM Studio, vLLM, OpenAI, OpenRouter.
The server applies the model's own chat template, which usually gives better answers than `/completion`.
```json
{
  "ai_provider": "openai",
  "openai_base_url": "http://127.0.0.1:8080/v1",
  "openai_model": "local-model",
  "openai_api_key": ""
}
```
Ollama: `"openai_base_url": "http://127.0.0.1:11434/v1"`, `"openai_model": "qwen2.5:7b"`.

### 3. Google Gemini
```json
{
  "ai_provider": "google_assistant",
  "google_assistant_api_key": "YOUR_API_KEY",
  "google_model": "gemini-2.5-flash"
}
```

### Fallback chain
If the main provider fails, the next one is tried. If all fail, a built-in phrase is spoken.
```json
{
  "ai_provider": "llama",
  "ai_fallback_providers": ["google_assistant"]
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
- `ai_provider`: `llama`, `openai` or `google_assistant` (alias `gemini`)
- `ai_fallback_providers`: list of backup providers
- `target_apps`: List of target applications
- `reminder_interval`: Time until reminder (seconds)
- `punishment_interval`: Time until AI "punishment" (seconds)
- `punishment_cooldown`: Minimum pause between AI punishments (seconds, default = `punishment_interval`)
- `praise_interval`: Time for AI "praise" (seconds)

### AI behaviour:
- `prompt`: persona / system prompt
- `assistant_name`: persona name (by default taken from the old `punishment_subprompt`, else `Ева`)
- `punishment_instruction`, `praise_instruction`, `fact_instruction`: event prompts with placeholders
  `{target}`, `{distraction}`, `{distracted_seconds}`, `{count}`, `{minutes}`, `{seconds}`.
  Old `*_subprompt` keys still work.
- `ai_response_rules`: extra rules added to the system prompt (short replies, no emoji, etc.)
- `ai_history_size`: how many recent messages to send as dialogue history (default 0 = off).
  Small local models copy their own previous replies from history, so keep it 0 for them;
  for large models (Gemini, GPT) 6–10 can make replies more coherent
- `ai_event_log_size`: how many recent events (distractions, praise, facts, finished sessions)
  the model sees as a compact timestamped log (default 8). Gives continuity without copying
- `ai_style_hints`: `{"punishment": [...], "praise": [...]}` random style hint added to each request
  (e.g. "joke about it", "be strict"), never the same twice in a row
- `ai_fact_topics`: list of fact topics; a random one is picked, excluding recent ones
- `ai_repeat_threshold`: similarity (0..1, default 0.6) above which a reply counts as a repeat.
  A repeat is re-asked once with a hint, then replaced with a fallback phrase
- `ai_context_budget`: max prompt size in tokens (default 1500). Oldest history and events are
  dropped to fit. If the server still reports a context overflow, the budget is halved automatically
- `ai_memory_file`: where history, event log, recent replies and facts are saved (default
  `assistant_memory.json`, `null` = off). Facts are kept across days, the rest only for the current day
- `ai_max_chars`: max reply length passed to TTS (default 400)
- `ai_max_sentences`: hard limit of sentences in a reply (default 2, 0 = off). Small models ignore "be brief"
- `ai_drop_questions`: remove trailing questions from replies (default true), the user can't answer by voice
- `fallback_phrases`: `{"punishment": [...], "praise": [...], "fact": [...]}` spoken when AI is unavailable
- `ai_timeout`, `ai_retries`: request timeout (s) and retry count (default 30 and 2)

### llama.cpp Parameters:
- `llama_url`: `/completion` endpoint URL
- `llama_user_label`: speaker label for events in the transcript (default `System`)
- `api_key`: sent as `Authorization: Bearer`
- `temperature`, `n_predict`, `top_k`, `top_p`, `min_p`, `stop`, ...: sampling parameters

### OpenAI-compatible Parameters:
- `openai_base_url`, `openai_model`, `openai_api_key`
- `openai_max_tokens`: reply token limit (default 300)
- `openai_temperature`, `openai_top_k`, `openai_top_p`, `openai_min_p`, `openai_presence_penalty`,
  `openai_frequency_penalty`, `openai_repeat_penalty`: sent **only if set**
- `openai_thinking`: allow reasoning (default `false`)
- `openai_extra_params`: any extra request fields (applied last, override everything)

Like the llama.cpp web UI, the client does not send sampling parameters by default.
The server then uses its launch flags and the recommended values the model authors put
into the GGUF metadata (e.g. LFM2.5 ships temperature 0.1 and top_k 50). Overriding them with
generic values usually makes small models worse.

Reasoning models (LFM2.5, Qwen3, ...) can spend the whole token limit on thinking and return an
empty reply. With `openai_thinking: false` the client sends `chat_template_kwargs.enable_thinking=false`
(Qwen-style templates, same as the web UI) and `thinking_budget_tokens=0` (templates that always
open `<think>`, e.g. LFM2.5).

Tip: do not put example phrases into prompts and rules. Small models copy them into every reply.

### Text-to-speech:
Replies are spoken by the first working engine in the chain. If an engine fails, the next one
speaks, and the failed one is skipped for `tts_failure_cooldown` seconds (default 600), then retried.
- `tts_engines`: chain order (default `["silero", "edge", "piper", "sapi"]`)
- `silero`: offline [Silero](https://github.com/snakers4/silero-models) voices on CPU, natural Russian
  with auto-stress, ~0.1 s per phrase, ~600 MB RAM. Needs PyTorch (CPU build, installed by `start.bat`:
  `pip install torch --index-url https://download.pytorch.org/whl/cpu`) and the model
  `voices/silero_v5_6_ru.pt` (downloaded by `start.bat`). Model license: CC BY-NC 4.0 (non-commercial).
  `silero_speaker`: `xenia` (default), `baya`, `kseniya`, `aidar`, `eugene`;
  `silero_rate`: `x-slow`..`x-fast`, `silero_pitch`: `x-low`..`x-high` (SSML prosody);
  `silero_sample_rate` (default 48000), `silero_threads` (default 8)
- `edge`: Microsoft Edge online voices, best quality. Unofficial API: if it starts failing with
  `403`, update the package: `pip install -U edge-tts`.
  `edge_tts_voice` (default `ru-RU-SvetlanaNeural`, also `ru-RU-DmitryNeural`), `edge_tts_rate` (e.g. `"+10%"`)
- `piper`: offline [Piper](https://github.com/rhasspy/piper) voices, good quality, ~0.7 s per phrase on CPU.
  `piper_model` (default `voices/ru_RU-irina-medium.onnx`, downloaded by `start.bat`),
  `piper_length_scale` (>1 slower, <1 faster). Other Russian voices: `denis`, `dmitri`, `ruslan` from
  [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU)
- `sapi`: built-in Windows voices, offline, nothing to install. `sapi_voice` (default `Irina`), `sapi_rate` (-10..10)

### Audio output:
- `audio_frequency`: mixer sample rate (default 48000, matches most Windows devices)
- `audio_buffer`: mixer buffer in samples (default 2048). If you still hear crackling, try 4096
- `reminder_volume`: warning sound volume 0..1 (default 1.0)

The warning sound and speech are decoded once into memory and play on separate channels,
so the warning does not cut off speech.

### Gemini Parameters:
- `google_assistant_api_key`: API key (sent in a header, not in the URL)
- `google_model`: model name (default `gemini-2.5-flash`)
- `google_max_tokens`, `google_temperature`, `google_top_p`, `google_top_k`
- `google_thinking_budget`: thinking token budget (0 by default for 2.5-flash so short replies are not cut off)

## File Structure  

```  
workReminder/  
├── main.py              # Main script  
├── ai_client.py         # AI providers (llama.cpp, OpenAI-compatible, Gemini)  
├── assistant.py         # Prompts, context, dialogue memory, TTS cleanup  
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