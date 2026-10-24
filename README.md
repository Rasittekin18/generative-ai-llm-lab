# 🤖 Generative AI, LLM & NLP Laboratory

<div align="center">

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-v0.2%2B-green?logo=langchain&logoColor=white)
![Hugging Face](https://img.shields.io/badge/Hugging%20Face-Transformers-yellow?logo=huggingface&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.x-red?logo=pytorch&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agents-purple)
![License](https://img.shields.io/badge/License-MIT-teal)

<br/>

**A state-of-the-art monorepo covering Large Language Models (LLMs), Retrieval-Augmented Generation (RAG), LangChain, LangGraph, Hugging Face Transformers, Fine-Tuning (PEFT/LoRA), and Classic NLP.**  
Developed by **[Raşit Tekin](https://github.com/Rasittekin18)**.

[Modüller](#-modüller-ve-koleksiyonlar) • [Kurulum & Hazırlık](#-kurulum-ve-genel-kullanım) • [Teknolojiler](#-kullanılan-teknolojiler) • [İletişim](#-yazar)

</div>

---

## 📌 Genel Bakış (Overview)

Bu depo; klasik Doğal Dil İşleme (NLP) temellerinden başlayarak günümüzün en güncel **Üretken Yapay Zeka (Generative AI)**, **LLM Ajanları (Agents)**, **Gelişmiş RAG boru hatları** ve **Açık Kaynak Model Fine-Tuning** (Mistral 7B, PEFT/LoRA) uygulamalarını içeren kapsamlı bir laboratuvardır.

Tüm projeler kendi alt klasörlerinde modüler yapısını, kaynak kodlarını ve notebook'larını koruyarak organize edilmiştir.

---

## 📂 Modüller ve Koleksiyonlar

| # | Modül / Proje | Odak Alanı & İçerik | Temel Teknolojiler | Klasör Linki |
| :-: | :--- | :--- | :--- | :-: |
| 01 | **LangChain & RAG Applications** | Çeviri uygulamaları, bellekli sohbet botları, vektör veri tabanları (Vector Stores), ReAct ajanları ve LangGraph ile gelişmiş RAG mimarileri. | LangChain, LangGraph, Chroma/FAISS, OpenAI | [`/ai-applications-langchain-rag`](./ai-applications-langchain-rag) |
| 02 | **Building AI Apps with LangChain** | LLM zincirleri (Chains), Prompt Template mühendisliği ve harici araçları kullanan akıllı ajanlar. | LangChain, Python | [`/Building-AI-Applications-with-LangChain-LLMs`](./Building-AI-Applications-with-LangChain-LLMs) |
| 03 | **Hugging Face Transformers & GenAI** | Pipeline pratikleri, duygu analizi, çok dilli Varlık İsmi Tanıma (NER), Gradio arayüzleri, Mistral-7B metin üretimi, Fine-Tuning ve PEFT/LoRA. | Transformers, PyTorch, Gradio, Mistral-7B, PEFT | [`/generative-ai-nlp-huggingface`](./generative-ai-nlp-huggingface) |
| 04 | **Generative AI Master Handbook** | LLM iş akışları, RAG konseptleri, Chatbot geliştirme adımları ve Görme-Dil Modelleri (Vision-Language Models - VLM). | PyTorch, LLMs, Multimodal AI | [`/Generative_AI`](./Generative_AI) |
| 05 | **Comprehensive NLP Fundamentals** | Tokenization, Stemming, Lemmatization, POS Tagging, Word2Vec, GloVe, Nöral Makine Çevirisi (NMT) ve Görsel Başlıklandırma (Image Captioning). | NLTK, spaCy, Gensim, PyTorch | [`/Natural-Language-Processing-NLP-`](./Natural-Language-Processing-NLP-) |
| 06 | **IMDB Sentiment Analysis** | Film incelemeleri üzerinde metin ön işleme, vektörleştirme ve sınıflandırma modelleriyle duygu analizi. | Scikit-Learn, NLTK, Python | [`/IMDB-Sentiment-Analysis`](./IMDB-Sentiment-Analysis) |

---

## 🚀 Kurulum ve Genel Kullanım

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/Rasittekin18/generative-ai-llm-lab.git
cd generative-ai-llm-lab
```

### 2. Sanal Ortam Oluşturun
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Bağımlılıkları Yükleyin
```bash
pip install langchain langchain-community langgraph transformers torch datasets accelerate peft gradio faiss-cpu nltk spacy scikit-learn
```

### 4. Ortam Değişkenlerini (API Anahtarlarını) Ayarlayın
LangChain veya OpenAI tabanlı projeleri çalıştırmak için proje dizininde bir `.env` dosyası oluşturun:
```env
OPENAI_API_KEY="your-openai-api-key"
HUGGINGFACEHUB_API_TOKEN="your-hf-token"
```

### 5. Jupyter Notebook'ları Başlatın
```bash
jupyter notebook
```
İlgili klasöre girerek interaktif adımları inceleyebilir veya scriptleri doğrudan çalıştırabilirsiniz:
```bash
# Örnek: IMDB Duygu Analizini Çalıştırma
cd IMDB-Sentiment-Analysis
python IMDB_Sentiment_Analysis.py
```

---

## 🛠️ Kullanılan Teknolojiler

- **LLM Orkestrasyonu & Ajanlar:** LangChain, LangGraph
- **Model Kütüphaneleri & Transformers:** Hugging Face Transformers, Accelerate, PEFT (Parameter-Efficient Fine-Tuning)
- **Derin Öğrenme Çatısı:** PyTorch
- **Vektör Veri Tabanları & Geri Çağırma (Retrieval):** FAISS, ChromaDB
- **Doğal Dil İşleme (NLP):** NLTK, spaCy, Gensim
- **Arayüz & Dağıtım:** Gradio, Streamlit

---

## 👨‍💻 Yazar

**Raşit Tekin**  
*Electronics Engineer \| AI & Data Science*  
- GitHub: [@Rasittekin18](https://github.com/Rasittekin18)  
- E-posta: [rasittekin18@gmail.com](mailto:rasittekin18@gmail.com)  
- Konum: İstanbul, Türkiye

---

## 📄 Lisans

Bu projedeki tüm çalışmalar **MIT Lisansı** altında sunulmaktadır.
