# training/finetune.py
#
# Fine-tune LLaMA 3.1 8B on cloud architecture pairs using QLoRA.
#
# Prerequisites:
#   pip install transformers peft trl bitsandbytes accelerate datasets
#
# Run (single GPU, e.g. A100 on SageMaker or RunPod):
#   python -m training.finetune --data data/finetune/pairs.jsonl
#
# What this does:
#   - Loads LLaMA 3.1 8B in 4-bit (NF4) quantization via bitsandbytes
#   - Attaches LoRA adapters to attention layers (r=16, alpha=32)
#   - Fine-tunes for 3 epochs on your Alpaca-style pairs
#   - Saves the LoRA adapter weights (not the full model — much smaller)
#   - The adapter is then merged into the base model for inference
#
# GPU requirements:
#   - Minimum: 1x A10G (24GB VRAM) — fits with QLoRA
#   - Recommended: 1x A100 (40GB) — faster, allows larger batch
#   - Cost: ~$3-6/hour on RunPod or SageMaker for an A100

import os
import sys
import json
import logging
import argparse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# This wraps each (instruction, response) pair into the format the model learns.
# At inference time, we format the query the same way and let the model complete it.

PROMPT_TEMPLATE = """Below is an instruction that describes a cloud architecture task.
Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Response:
{response}"""

INFERENCE_TEMPLATE = """Below is an instruction that describes a cloud architecture task.
Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Response:
"""


def format_prompt(example: dict) -> str:
    """Format one training example into the Alpaca prompt."""
    return PROMPT_TEMPLATE.format(
        instruction=example["instruction"],
        response=example["response"],
    )


def load_dataset_from_jsonl(path: str):
    """Load pairs.jsonl and return a HuggingFace Dataset."""
    from datasets import Dataset

    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    logger.info(f"Loaded {len(records)} training pairs from {path}")
    dataset = Dataset.from_list(records)

    # Add the formatted prompt column
    dataset = dataset.map(lambda ex: {"text": format_prompt(ex)})
    return dataset


def train(
    data_path:     str,
    output_dir:    str  = "models/cloud-architect-lora",
    base_model:    str  = "meta-llama/Llama-3.1-8B-Instruct",
    num_epochs:    int  = 3,
    batch_size:    int  = 4,
    grad_accum:    int  = 4,    # effective batch = batch_size * grad_accum = 16
    learning_rate: float = 2e-4,
    max_seq_len:   int  = 2048,
    lora_r:        int  = 16,
    lora_alpha:    int  = 32,
    lora_dropout:  float = 0.05,
):
    """Fine-tune LLaMA 3.1 8B with QLoRA on cloud architecture pairs.

    Args:
        data_path:     path to pairs.jsonl
        output_dir:    where to save the LoRA adapter weights
        base_model:    HuggingFace model ID (needs HF token for Llama gated models)
        num_epochs:    training epochs (3 is standard for instruction fine-tuning)
        batch_size:    per-device batch size (reduce if OOM)
        grad_accum:    gradient accumulation steps
        learning_rate: AdamW learning rate
        max_seq_len:   max token length (our responses are long, 2048 is safe)
        lora_r:        LoRA rank (16 = good tradeoff between quality and size)
        lora_alpha:    LoRA scaling factor (usually 2x rank)
        lora_dropout:  LoRA dropout regularization
    """
    try:
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from trl import SFTTrainer, SFTConfig
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Run: pip install transformers peft trl bitsandbytes accelerate datasets")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    #  1. Load dataset 
    dataset = load_dataset_from_jsonl(data_path)
    logger.info(f"Dataset size: {len(dataset)} examples")

    #  2. Quantization config (4-bit NF4) 
    # QLoRA: quantize the base model to 4-bit, train only the LoRA adapters in bf16.
    # This lets an 8B model fit in ~10GB VRAM instead of ~32GB.
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",           # NF4 = best quality 4-bit format
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,      # double quantization saves ~0.4 bits/param
    )

    #  3. Load base model 
    logger.info(f"Loading base model: {base_model}")
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"   # avoid warning with causal LM

    #  4. LoRA config 
    # We attach LoRA to the attention projection layers — these are the most
    # important for learning the output format and domain knowledge.
    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[            # LLaMA 3 attention layer names
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",   # also MLP layers for better format learning
        ],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()   # shows ~1-2% of params are trainable

    #  5. Training arguments 
    # TRL 1.x uses SFTConfig (superset of TrainingArguments) — dataset_text_field,
    # max_seq_length, and packing live here instead of in SFTTrainer directly.
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        optim="paged_adamw_32bit",   # paged optimizer — reduces memory spikes
        report_to="none",            # set to "wandb" if you want loss tracking
        run_name="cloud-architect-lora",
        dataloader_num_workers=0,
        dataset_text_field="text",
        max_seq_length=max_seq_len,
        packing=False,
    )

    #  6. Trainer 
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        processing_class=tokenizer,
    )

    #  7. Train 
    logger.info("Starting training...")
    trainer.train()

    #  8. Save LoRA adapter 
    final_path = os.path.join(output_dir, "final")
    trainer.save_model(final_path)
    tokenizer.save_pretrained(final_path)
    logger.info(f"LoRA adapter saved to: {final_path}")
    logger.info("Next step: merge the adapter into the base model with merge_adapter.py")



def merge_adapter(
    base_model: str = "meta-llama/Llama-3.1-8B-Instruct",
    adapter_path: str = "models/cloud-architect-lora/final",
    output_path: str  = "models/cloud-architect-merged",
):
    """Merge LoRA adapter weights into the base model for faster inference.

    The merged model can be used with vLLM or loaded directly without PEFT.

    Args:
        base_model:   HuggingFace model ID
        adapter_path: path to saved LoRA adapter
        output_path:  where to save the merged model
    """
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
        import torch
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        sys.exit(1)

    logger.info("Loading base model for merge (full precision)...")
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.float16,
        device_map="cpu",       # merge on CPU to avoid VRAM limits
    )
    tokenizer = AutoTokenizer.from_pretrained(adapter_path)

    logger.info("Loading LoRA adapter...")
    model = PeftModel.from_pretrained(base, adapter_path)

    logger.info("Merging weights...")
    model = model.merge_and_unload()

    os.makedirs(output_path, exist_ok=True)
    model.save_pretrained(output_path)
    tokenizer.save_pretrained(output_path)
    logger.info(f"Merged model saved to: {output_path}")
    logger.info("You can now load this as a standard HuggingFace model.")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune or merge the cloud architect model.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # train subcommand
    train_parser = subparsers.add_parser("train", help="Fine-tune with QLoRA")
    train_parser.add_argument("--data",     default="data/finetune/pairs.jsonl")
    train_parser.add_argument("--output",   default="models/cloud-architect-lora")
    train_parser.add_argument("--model",    default="meta-llama/Llama-3.1-8B-Instruct")
    train_parser.add_argument("--epochs",   type=int,   default=3)
    train_parser.add_argument("--batch",    type=int,   default=4)
    train_parser.add_argument("--lr",       type=float, default=2e-4)
    train_parser.add_argument("--lora-r",   type=int,   default=16)

    # merge subcommand
    merge_parser = subparsers.add_parser("merge", help="Merge LoRA adapter into base model")
    merge_parser.add_argument("--base",    default="meta-llama/Llama-3.1-8B-Instruct")
    merge_parser.add_argument("--adapter", default="models/cloud-architect-lora/final")
    merge_parser.add_argument("--output",  default="models/cloud-architect-merged")

    args = parser.parse_args()

    if args.command == "train":
        train(
            data_path=args.data,
            output_dir=args.output,
            base_model=args.model,
            num_epochs=args.epochs,
            batch_size=args.batch,
            learning_rate=args.lr,
            lora_r=args.lora_r,
        )
    elif args.command == "merge":
        merge_adapter(
            base_model=args.base,
            adapter_path=args.adapter,
            output_path=args.output,
        )
