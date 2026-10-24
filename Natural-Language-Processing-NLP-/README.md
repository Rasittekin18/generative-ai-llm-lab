# 🚀 Doğal Dil İşleme A-Z™: (NLP) Course & Project Repository

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![TensorFlow](https://img.shields.io/badge/TensorFlow-2.x-orange?style=for-the-badge&logo=tensorflow)
![Keras](https://img.shields.io/badge/Keras-Deep%20Learning-red?style=for-the-badge&logo=keras)
![Gensim](https://img.shields.io/badge/Gensim-Word2Vec%2FGloVe-green?style=for-the-badge)
![NLTK](https://img.shields.io/badge/NLTK-Text%20Processing-yellow?style=for-the-badge)

Bu depo, **"Doğal Dil İşleme A-Z™: (NLP)"** kursu boyunca öğrenilen teorik NLP kavramlarını, kelime vektörü modellerini, derin öğrenme mimarilerini (RNN, LSTM, GRU) ve geliştirilen endüstriyel boyuttaki **3 ana projeyi** içermektedir.

---

## 📌 İçindekiler
- [Proje & Müfredat Özeti](#-proje--müfredat-özeti)
- [Öne Çıkan Projeler](#-öne-çıkan-projeler)
  - [1. Sentiment Analysis (Duygu Analizi)](#1-sentiment-analysis-duygu-analizi)
  - [2. Neural Machine Translation (Seq2Seq Makine Çevirisi)](#2-neural-machine-translation-seq2seq-makine-çevirisi)
  - [3. Image Captioning (Görsel Açıklama Oluşturma)](#3-image-captioning-görsel-açıklama-oluşturma)
- [Kullanılan Teknolojiler ve Kütüphaneler](#-kullanılan-teknolojiler-ve-kütüphaneler)
- [Dizin Yapısı](#-dizin-yapısı)
- [Kurulum ve Çalıştırma](#-kurulum-ve-çalıştırma)

---

## 📚 Proje & Müfredat Özeti

Kurs müfredatı kapsamında aşağıdaki temel ve ileri seviye Doğal Dil İşleme konuları teorik ve uygulamalı olarak işlenmiştir:

1. **Doğal Dil İşlemeye Giriş ve NLTK:**
   - Tokenization (Kelime ve Cümle bazlı)
   - Stop Words Temizleme
   - Stemming (PorterStemmer) ve Lemmatizing (WordNetLemmatizer)
   - Part of Speech Tagging (POS Tagging) & Named Entity Recognition (NER)
   - Corpus / Corpora Kavramları (Gutenberg, Wikipedia, Common Crawl vb.)

2. **Kelime Vektörleri (Word Embeddings):**
   - **word2vec:** Skip-gram, CBOW mimarileri, Negative Sampling, Softmax optimizasyonu ve Hürriyet Gazetesi veri seti (400k+ cümle) ile model eğitimi.
   - **GloVe (Global Vectors):** Matris Ayrıştırma (SVD) ve Kelime Sayma Yöntemleri vs Word2Vec karşılaştırması, Standart Pre-trained GloVe (6B token / 100D) vektörlerinin yüklenmesi ve kelime matematiği ($King - Man + Woman = Queen$).
   - **t-SNE Görselleştirme:** Yüksek boyutlu kelime vektörlerinin 2D uzayda kümelenmesini görselleştirme.

3. **Yinelenen Sinir Ağları (RNN, LSTM, GRU):**
   - Ardışık veri işleme mantığı ve Hafıza Mekanizması (Hidden State).
   - Exploding Gradient (Patlayan) & Vanishing Gradient (Kaybolan) problemleri ve çözümleri (Gradient Clipping).
   - LSTM (Long Short-Term Memory) & GRU (Gated Recurrent Unit) Hücre Mimarileri.

---

## 🛠 Öne Çıkan Projeler

### 1. Sentiment Analysis (Duygu Analizi)
- **Açıklama:** Hepsiburada sitesinden toplanan 245.000+ gerçek kullanıcı yorumu üzerinde Türkçe duygu analizi.
- **Mimari:** Embedding Layer + 3 Katlı GRU / CuDNNGRU + Dense (Sigmoid Output).
- **Özellikler:** Custom Tokenization, Padding/Truncating, Özel test cümleleriyle duygu skoru tahmini.
- **Başarı:** Test veri setinde **%95+ Başarı Oranı (Accuracy)**.

### 2. Neural Machine Translation (Seq2Seq Makine Çevirisi)
- **Açıklama:** 470.000+ cümleden oluşan İngilizce - Türkçe paralel veri seti üzerinde çalışan uçtan uca (End-to-End) çeviri modeli.
- **Mimari:** Encoder-Decoder Mimarı (3 Katlı GRU / CuDNNGRU) + Pre-trained English GloVe Embedding.
- **Teknikler:** Custom TokenizerWrap Sınıfı, Pre-padding/Post-padding stratejileri, Custom Loss (Sparse Categorical Crossentropy / Masked Loss), `<start>` ve `<end>` marker yönetimi.

### 3. Image Captioning (Görsel Açıklama Oluşturma)
- **Açıklama:** Verilen bir resmi analiz edip içeriğini açıklayan İngilizce cümle üreten Hibrit (Computer Vision + NLP) model.
- **Veri Seti:** COCO Dataset (118.000+ Görsel & Her görsel için 5+ açıklama metni).
- **Mimari:** 
  - **Encoder (CV):** Transfer Learning ile dondurulmuş VGG16 (FC2 katmanından 4096 boyutlu Transfer Values çıkarma).
  - **Decoder (NLP):** RNN / GRU Tabanlı Metin Üretim Ağı.
- **Performans:** Resim öznitelikleri (Feature Extraction) önceden dizine önbelleklenerek (caching) eğitim hızı 20x artırılmıştır.

---

## 💻 Kullanılan Teknolojiler ve Kütüphaneler

- **Programlama Dili:** Python 3.8+
- **Derin Öğrenme Framework'leri:** TensorFlow 2.x, Keras
- **NLP & Vektör Kütüphaneleri:** Gensim, NLTK
- **Veri İşleme ve Analiz:** NumPy, Pandas, Scikit-Learn
- **Görselleştirme:** Matplotlib, t-SNE
- **Görüntü İşleme:** PIL (Pillow), VGG16 (Keras Applications)

---

## 📁 Dizin Yapısı

```text
Natural-Language-Processing-NLP-/
├── 01_NLTK_Temelleri/
│   └── nltk_basics.ipynb
├── 02_Kelime_Vektorleri/
│   ├── word2vec_gensim.ipynb
│   ├── glove_gensim.ipynb
│   └── tsne_visualization.ipynb
├── 03_Sentiment_Analysis/
│   ├── sentiment_analysis.ipynb
│   └── hepsiburada.csv
├── 04_Machine_Translation_Seq2Seq/
│   ├── nmt_seq2seq.ipynb
│   └── english_turkish_pairs.txt
└── 05_Image_Captioning/
    ├── image_captioning.ipynb
    └── coco_helper.py
```

## ⚙️ Kurulum ve Çalıştırma

1. **Depoyu klonlayın:**

   ```bash
   git clone https://github.com/Rasittekin18/Natural-Language-Processing-NLP-.git
   cd Natural-Language-Processing-NLP-
   ```

2. **Gerekli bağımlılıkları yükleyin:**

   ```bash
   pip install -r requirements.txt
   ```

   *(Eğer GPU desteği kullanacaksanız `tensorflow-gpu` sürümünü yüklediğinizden emin olun).*

3. **Jupyter Notebook'u başlatın:**

   ```bash
   jupyter notebook
   ```
