# 🎬 IMDB Duygu Analizi (Sentiment Analysis with Recurrent Neural Networks - RNN)

Bu proje, **IMDB Film Yorumları (Movie Reviews)** veri setini kullanarak metin verileri üzerinde duygu analizi (**Sentiment Analysis**) gerçekleştirmeyi amaçlayan bir Derin Öğrenme (**Deep Learning**) çalışmasıdır.

Projede doğal dil işleme (**NLP**) ön işleme adımları (Padding, Tokenization & Vocabulary Sınırlaması) ve Metin dizilerini (**Sequences**) işlemek üzere Keras/TensorFlow altyapısı ile bir **Recurrent Neural Network (RNN)** modeli kurulup eğitilmiştir.

---

## 📋 Proje Yapısı ve Akış Şeması

Proje mimarisi aşağıdaki işlem adımlarını sırasıyla takip eder:

```text
[1. IMDB Veri Yükleme & EDA] ➔ [2. Kelime Sayısı & Dizi Uzunluğu Analizi]
                                                 │
[5. Model Değerlendirme & Metrikler] ◄─ [4. RNN Eğitimi & Epochs] ◄─ [3. Preprocessing (Padding & Truncation)]
```

---

## 📊 Veri Seti Özellikleri (Dataset Description)

- **Kaynak:** Keras `keras.datasets.imdb` Veri Seti
- **Toplam Yorum Sayısı:** 50.000 Film Yorumu (25.000 Eğitim / 25.000 Test)
- **Hedef Değişken (Target):** Binary Duygu Sınıfı
  - `0`: Olumsuz Yorum (Negative Review)
  - `1`: Olumlu Yorum (Positive Review)
- **Sözlük Boyutu (Vocabulary Constraints):** En çok kullanılan 15.000 kelime seçilmiştir (`num_words = 15000`).
- **Dizi Uzunluğu (Sequence Length):** Sabit dizilim için maksimum uzunluk 130 olarak belirlenmiştir (`maxlen = 130`).

---

## 🛠️ Kullanılan Teknolojiler ve Kütüphaneler

- **Programlama Dili:** Python 3.x
- **Veri Analizi & Görselleştirme:** `numpy`, `matplotlib`, `seaborn`, `scipy.stats`
- **Derin Öğrenme & NLP Framework:** `Keras` / `TensorFlow`
  - `Embedding` Layer (Kelime Vektörü Temsili)
  - `SimpleRNN` Layer (Zamana Bağlı Sıralı Veri İşleme)
  - `Dense` & `Activation("sigmoid")` (İkili Sınıflandırma Çıkış Katmanı)
  - `pad_sequences` (Metin dizilerini eşit uzunluğa tamamlama)

---

## ⚙️ Model Mimarisi ve Hiperparametreler

RNN modeli aşağıdaki katman dizilimi ile oluşturulmuştur:

1. **Embedding Layer:**
   - Input Dimension: `15,000` (En sık kelimeler)
   - Output Dimension: `32` (Vektör yoğunluğu)
   - Input Length: `130`
2. **SimpleRNN Layer:**
   - Units: `16`
   - Activation: `ReLU`
3. **Dense Layer & Activation:**
   - Units: `1`
   - Activation: `Sigmoid` (Binary Classification)

### Model Derleme & Eğitim Parametreleri:
- **Loss Function:** `binary_crossentropy`
- **Optimizer:** `RMSprop`
- **Batch Size:** `128`
- **Epochs:** `5`

---

## 📊 Modelleme ve Deney Sonuçları

| Metrik | Değer | Açıklama |
| :--- | :---: | :--- |
| **Test Accuracy** | **~%83.5 - %85.0** | Test seti üzerindeki genel sınıflandırma başarımı. |
| **Test Loss** | **~0.40 - 0.45** | İkili çapraz entropi (Binary Crossentropy) kayıp değeri. |
| **Optimal Epoch** | **Epoch 3 - 4** | Eğitim sırasında overfitting engeli için ideal epoch aralığı. |

---

## 🚀 Projenin Çalıştırılması

1. Bu depoyu klonlayın:
```bash
git clone https://github.com/kullanici_adi/imdb-sentiment-analysis-rnn.git
cd imdb-sentiment-analysis-rnn
```

2. Gerekli kütüphaneleri yükleyin:
```bash
pip install numpy matplotlib seaborn scipy tensorflow keras
```

3. Python scriptini çalıştırın:
```bash
python main.py
```

---

##  Notlar

- **Vocabulary & Sequence Tuning:** `num_words` ve `maxlen` parametreleri değiştirilerek model boyutunun ve bilgi kaybının duygu analizi başarımı üzerindeki etkileri incelenebilir.
- **Overfitting Analizi:** Epoch sayısı arttıkça (Epoch > 4) eğitim loss'u düşerken test loss'unun yükselmeye başlaması modelin ezberlemeye (overfitting) meylini açıkça gösterir. `Dropout` katmanı veya `LSTM/GRU` hücreleri eklenerek genelleştirme kabiliyeti artırılabilir.
