# 🚀 Generative AI & NLP with Hugging Face

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?logo=pytorch&logoColor=white)
![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Transformers%20%7C%20PEFT%20%7C%20TRL-FFD21E)
![Gradio](https://img.shields.io/badge/Gradio-Deployment-orange?logo=gradio)
![License](https://img.shields.io/badge/License-MIT-green.svg)

Bu depo, **"Üretken Yapay Zeka: Hugging Face ile Doğal Dil İşleme (NLP)"** kursu kapsamında geliştirilen teorik anlatımları, Jupyter/Colab not defterlerini, model fine-tuning çalışmalarını ve uçtan uca deployment projelerini içerir.

Geleneksel NLP yaklaşımlarından **Büyük Dil Modellerine (LLM)**, **PEFT/LoRA** ile parametre verimli ince ayardan **Gradio & Hugging Face Spaces** ile canlı servise kadar modern bir NLP çalışma alanı sunar.

---

## 📌 İçindekiler

- [🎯 Proje Özeti ve Hedefler](#-proje-özeti-ve-hedefler)
- [🛠 Öne Çıkan Modeller ve Teknolojiler](#-öne-çıkan-modeller-ve-teknolojiler)
- [📂 Repository Yapısı](#-repository-yapısı)
- [📖 Modül Detayları ve Müfredat](#-modül-detayları-ve-müfredat)
- [💻 Kurulum ve Çalıştırma](#-kurulum-ve-çalıştırma)
- [✉️ İletişim & Katkıda Bulunma](#️-iletişim--katkıda-bulunma)

---

## 🎯 Proje Özeti ve Hedefler

Bu repodaki temel amaç yalnızca hazır kütüphaneleri kullanmak değil; **Attention, Self-Attention, Encoder-Decoder ve Transformer** gibi mimarilerin mantığını anlayarak gerçek dünya problemlerine yönelik optimize edilmiş NLP modelleri geliştirmektir.

### Temel Kazanımlar

- **Transformer Mimarisi:** Attention, Self-Attention ve Transfer Learning mantığı
- **Model Eğitimi:** PyTorch ve Hugging Face `Trainer` API
- **Çok Dilli NLP:** XLM-RoBERTa ile multilingual NER
- **LLM Fine-Tuning:** Quantization, PEFT, LoRA ve QLoRA
- **Metin Üretimi:** Greedy, Beam Search, Top-k ve Top-p
- **Deployment:** Gradio ve Hugging Face Spaces ile model sunumu

---

## 🛠 Öne Çıkan Modeller ve Teknolojiler

| Alan | Kullanılan Model / Teknoloji | Açıklama |
| :--- | :--- | :--- |
| **Metin Sınıflandırma** | `DistilBERT` | Emotion veri seti üzerinde duygu analizi |
| **Token Sınıflandırma** | `XLM-RoBERTa` | Çok dilli NER uygulaması |
| **Metin Üretimi** | `GPT-2`, `Mistral-7B`, `Phi-4 Mini` | Farklı text generation stratejileri |
| **LLM Fine-Tuning** | `Mistral-7B`, `BitsAndBytes`, `LoRA` | 4-bit quantization ve adapter tabanlı fine-tuning |
| **Deployment** | `Gradio`, `Hugging Face Spaces` | İnteraktif web arayüzleri ve cloud deployment |

---

## 📂 Repository Yapısı

```text
generative-ai-nlp-huggingface/
├── 01_transformers_intro/
│   └── 01_pipelines_and_intro.ipynb
├── 02_text_classification/
│   └── 02_sentiment_analysis.ipynb
├── 03_token_classification/
│   ├── 03_multilingual_ner.ipynb
│   └── app_gradio_ner.py
├── 04_text_generation/
│   └── 04_text_generation_strategies.ipynb
├── 05_working_with_llms/
│   ├── 05_mistral_7b_intro.ipynb
│   └── 06_mistral_7b_instruct.ipynb
├── 06_llm_finetuning/
│   ├── 07_quantization_bitsandbytes.ipynb
│   ├── 08_peft_lora_finetuning.ipynb
│   └── 09_peft_inference.ipynb
├── 07_end_to_end_project/
│   ├── app.py
│   └── requirements.txt
└── README.md
```

---

## 📖 Modül Detayları ve Müfredat

### 1. Transformers & Hugging Face Ekosistemi

- Attention ve Self-Attention mekanizmaları
- Hugging Face `pipeline` kullanımı
- Sentiment Analysis
- Zero-Shot Classification
- Text Generation
- NER
- Question Answering
- Summarization
- Translation
- Automatic Speech Recognition

### 2. Metin Sınıflandırma

- Emotion veri seti
- Subword Tokenization
- WordPiece & BPE
- Token IDs ve Attention Mask
- DistilBERT
- PyTorch & `Trainer` API
- Confusion Matrix ile hata analizi

### 3. Token Sınıflandırma – Multilingual NER

- Token bazlı sınıflandırma
- XLM-RoBERTa
- SentencePiece tokenizer
- Token Alignment
- `-100` / `ignore_index`
- Cross-Lingual NER

### 4. Metin Üretim Stratejileri

- Auto-regressive modeller
- Greedy Search
- Beam Search
- Temperature
- Top-k Sampling
- Top-p / Nucleus Sampling
- `no_repeat_ngram_size`

### 5. Büyük Dil Modelleri

- Mistral 7B
- Sliding Window Attention
- Base Model
- Fine-Tuned Model
- Instruct Model
- RLHF / DPO
- Chat Templates
- `tokenizer.apply_chat_template`

### 6. Parameter-Efficient Fine-Tuning

- 32-bit / 16-bit → 4-bit Quantization
- BitsAndBytes
- NF4
- LoRA
- QLoRA
- PEFT
- SFTTrainer
- Databricks Dolly 15k
- Hugging Face Hub

### 7. Uçtan Uca Deployment

- Gradio arayüzleri
- Hugging Face Spaces
- Model servisleştirme
- Kullanıcı etkileşimli NLP uygulamaları

---

## 💻 Kurulum ve Çalıştırma

### 1. Repoyu Klonlayın

```bash
git clone https://github.com/Rasittekin18/generative-ai-nlp-huggingface.git
cd generative-ai-nlp-huggingface
```

### 2. Sanal Ortam Oluşturun

#### Conda

```bash
conda create -n hf-nlp python=3.10 -y
conda activate hf-nlp
```

#### Venv

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

Linux / macOS:

```bash
source venv/bin/activate
```

### 3. Kütüphaneleri Yükleyin

```bash
pip install --upgrade pip
pip install torch torchvision torchaudio
pip install transformers datasets peft trl bitsandbytes gradio accelerate evaluate
```

### 4. Gradio Uygulamasını Başlatın

```bash
python 03_token_classification/app_gradio_ner.py
```

---

## ✉️ İletişim & Katkıda Bulunma

Projeyle ilgili soru, öneri veya katkılarınız için GitHub üzerinden **Issue** açabilirsiniz.

- **Website:** https://rasittekin.com/
- **GitHub:** https://github.com/Rasittekin18

---

> Bu çalışma, **"Üretken Yapay Zeka: Hugging Face ile Doğal Dil İşleme (NLP)"** kursu kapsamında gerçekleştirilen teorik ve pratik çalışmalar doğrultusunda hazırlanmıştır.
