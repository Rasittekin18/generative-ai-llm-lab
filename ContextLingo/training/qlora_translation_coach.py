"""Bölüm 6 (QLoRA & PEFT) Köprüsü: Kendi Bağlamsal İngilizce-Türkçe Öğretmen Modelini Eğitme Şablonu.

Bu script Google Colab veya Kaggle T4 GPU üzerinde çalıştırılmak üzere hazırlanmıştır.
Eğittiğiniz LoRA adaptörünü Hugging Face Hub'a yükleyip masaüstü uygulamasına bağlayabilirsiniz.
"""

# !pip install -q -U transformers bitsandbytes peft datasets accelerate trl

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from trl import SFTTrainer

BASE_MODEL = "mistralai/Mistral-7B-v0.1"

# Örnek sentetik eğitim verisi (gerçek projede kendi çift dilli veri setinizi yükleyin)
SAMPLES = [
    {
        "instruction": "Bu İngilizce cümleyi bağlama göre Türkçeye çevir ve kelime analizi yap: 'Let's circle back on this after we ship the hotfix.'",
        "response": '{"natural_translation": "Acil düzeltmeyi yayınladıktan sonra bu konuya tekrar dönelim.", "nuance_explanation": "İş/yazılım bağlamında circle back daha sonra tekrar görüşmek, ship ise ürünü/güncellemeyi yayınlamak anlamında kullanılır.", "vocabulary": [{"word": "circle back", "meaning_tr": "konuya daha sonra tekrar dönmek", "cefr_level": "B2", "example_en": "Let us circle back next week."}]}',
    },
    {
        "instruction": "Türkçe mesajı Profesyonel tonda İngilizceye çevir: 'Dosyayı ekte gönderdim, fırsat bulunca inceleyebilir misiniz?'",
        "response": '{"english_result": "I have attached the file for your review—could you take a look when you get a chance?", "alternatives": ["Please find the file attached for your review."], "explanation_tr": "When you get a chance kalıbı kibar ve doğal bir iş İngilizcesi ifadesidir."}',
    },
]


def format_prompt(sample):
    return {"text": f"<s>[INST] {sample['instruction']} [/INST] {sample['response']}</s>"}


def main():
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, padding_side="right", add_eos_token=True)
    tokenizer.pad_token = tokenizer.eos_token

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="auto",
    )
    model.gradient_checkpointing_enable()
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=8,
        lora_alpha=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
        lora_dropout=0.05,
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    dataset = Dataset.from_list(SAMPLES).map(format_prompt)

    training_args = TrainingArguments(
        output_dir="./en-tr-coach-lora",
        per_device_train_batch_size=2,
        optim="paged_adamw_32bit",
        learning_rate=2e-4,
        max_steps=50,
        logging_steps=10,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        train_dataset=dataset,
        peft_config=lora_config,
        dataset_text_field="text",
    )
    model.config.use_cache = False
    trainer.train()
    # trainer.model.push_to_hub("kullanici-adiniz/mistral-7b-en-tr-coach")


if __name__ == "__main__":
    main()
