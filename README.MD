## STOP PROCRASTINATION
### BE PRODUCTIVE!

Python script to stay focus on applications for work.
One timer alert you every 5 second to get back to work,
second one uses AI to generate "Punishment" message.

***I was abandoned by one of my friends and no one can moral support me to work so I was trying enchanse my AI interface that was too much work, but one day I found out this solution and make it in one python script.*** 

*Hope u'll well stay focus!*

*JErfurt*


## Installation
Use Conda or Venv for reqs don't make mess with system. 
As an AI backend I use llama.cpp server, please checkout [llama.cpp](https://github.com/ggerganov/llama.cpp) it's incredibly easy to use!

**Okay, I'll add simple step-by-step guide for windows**

Copy repository, unpack, open folder with CMD

Create virtual environment
```
python -m venv venv
```
Apply environment
```
venv\Scripts\activate
```
Install dependencies
```
pip install -r requirements.txt
```
Go to [llama.cpp/releases](https://github.com/ggerganov/llama.cpp/releases) and download "..cu.." if you have CUDA or avx2 if only CPU or other compatible for your system, ok?.

Unpack llama.cpp release some where and you can start llama-server.exe with some params, but not that fast.

Firstly find some llama .GGUF models on [HuggingFace](https://huggingface.co/) recomend llama-3B, I hope I don't need to explain about quantization in here, if you need it find it with your self.

Finally start server and then main.py

If have CUDA set --n-gpu-layers
```
llama-server.exe -m Models/NAME_OF_YOUR_MODEL.gguf --n-gpu-layers 29 --split-mode layer --main-gpu 0 --ctx-size 4096
```

If CPU only
```
llama-server.exe -m Models/NAME_OF_YOUR_MODEL.gguf --ctx-size 4096
```

If you lose python virtual environment, let's get back to it
```
venv\Scripts\activate
```

Run main.py
```
python main.py
```

### It's easy to init, anyway I did some explain