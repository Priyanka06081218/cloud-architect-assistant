# modal_vllm.py
#
# Deploys the fine-tuned cloud-architect LLaMA 3.1 8B model on Modal
# using vLLM for fast inference with an OpenAI-compatible API.
#
# Usage:
#   modal run modal_vllm.py            # download model weights (run once)
#   modal deploy modal_vllm.py         # deploy persistently
#   modal serve modal_vllm.py          # run locally for testing
#
# Set VLLM_BASE_URL=https://<your-modal-app>--vllmserver-chat-completions.modal.run
# in your .env

import modal

#  Image 
vllm_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "vllm==0.6.6",
        "huggingface_hub",
        "hf_transfer",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App("cloud-architect-vllm")

#  Model config 
MODEL_ID = "Priyanka1218/cloud-architect-llama"
MODEL_DIR = "/model"
GPU = "A10G"      # 24GB VRAM — fits LLaMA 3.1 8B comfortably (~$1.10/hr)

#  Volume to cache model weights 
volume = modal.Volume.from_name("cloud-architect-model-cache", create_if_missing=True)


@app.function(
    image=vllm_image,
    gpu=GPU,
    timeout=600,
    volumes={MODEL_DIR: volume},
    secrets=[],
)
def download_model():
    """Download model weights into the persistent volume (run once)."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        MODEL_ID,
        local_dir=MODEL_DIR,
        ignore_patterns=["*.gguf", "*.ggml"],
    )
    print(f"Model downloaded to {MODEL_DIR}")
    volume.commit()


#  vLLM server 
@app.cls(
    image=vllm_image,
    gpu=GPU,
    timeout=300,
    volumes={MODEL_DIR: volume},
    secrets=[],
    scaledown_window=300,   # scale to zero after 5 min idle
)
@modal.concurrent(max_inputs=4)
class VLLMServer:
    @modal.enter()
    def load_model(self):
        from vllm import AsyncLLMEngine
        from vllm.engine.arg_utils import AsyncEngineArgs
        from transformers import AutoTokenizer

        args = AsyncEngineArgs(
            model=MODEL_DIR,
            dtype="auto",
            max_model_len=8192,
            gpu_memory_utilization=0.90,
            tensor_parallel_size=1,
            enforce_eager=False,
        )
        self.engine = AsyncLLMEngine.from_engine_args(args)
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        print("vLLM engine and tokenizer loaded.")

    @modal.fastapi_endpoint(method="POST", label="chat-completions")
    async def chat_completions(self, request: dict):
        from vllm import SamplingParams
        from vllm.utils import random_uuid

        messages = request.get("messages", [])
        temperature = request.get("temperature", 0.3)
        max_tokens = request.get("max_tokens", 1024)
        model = request.get("model", MODEL_ID)

        # Use the model's actual Llama 3 chat template
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        sampling_params = SamplingParams(
            temperature=temperature,
            max_tokens=max_tokens,
            stop_token_ids=[self.tokenizer.eos_token_id],
        )

        request_id = random_uuid()
        results_generator = self.engine.generate(prompt, sampling_params, request_id)

        final_output = None
        async for request_output in results_generator:
            final_output = request_output

        generated_text = final_output.outputs[0].text

        return {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion",
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": generated_text},
                "finish_reason": final_output.outputs[0].finish_reason,
            }],
            "usage": {
                "prompt_tokens": len(final_output.prompt_token_ids),
                "completion_tokens": len(final_output.outputs[0].token_ids),
                "total_tokens": len(final_output.prompt_token_ids) + len(final_output.outputs[0].token_ids),
            },
        }


@app.local_entrypoint()
def main():
    print("Downloading model weights to persistent volume...")
    download_model.remote()
    print("Done. Now run: modal deploy modal_vllm.py")
