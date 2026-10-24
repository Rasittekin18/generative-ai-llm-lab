# AI Applications with LangChain & RAG

LangChain ve LangGraph ekosistemini adım adım öğrenmek için hazırlanmış, sıfırdan geliştirilen örnek projeler koleksiyonu. Basit bir "chain" kurulumundan başlayıp; hafızalı chatbot'lara, vektör store tabanlı RAG (Retrieval Augmented Generation) sistemlerine, agent/ReAct mimarilerine ve son olarak LangGraph ile kurulan **kendini düzelten (self-correcting) ileri seviye bir RAG uygulamasına** kadar uzanan bir öğrenme yolculuğu sunar.

Her klasör, kendi başına çalıştırılabilen bağımsız bir modüldür ve kendi `requirements.txt` dosyasına sahiptir.

## 📚 Modüller

| Klasör | Konu | Öne Çıkan Kavramlar |
|---|---|---|
| [`01_langchain_intro_and_translation_app`](./01_langchain_intro_and_translation_app) | LangChain'e giriş, basit çeviri uygulaması | Prompt template, output parser, chain (`\|` operatörü), FastAPI + LangServe ile servis olarak yayınlama |
| [`02_simple_chatbot_and_memory_concepts`](./02_simple_chatbot_and_memory_concepts) | Basit chatbot ve hafıza (memory) kavramları | Mesaj geçmişi (chat history), streaming yanıtlar |
| [`03_vector_store_and_rag_concept`](./03_vector_store_and_rag_concept) | Vektör store ve RAG'e giriş | Embeddings, Chroma vektör veritabanı, benzerlik araması |
| [`04_retrieval_augmented_generation`](./04_retrieval_augmented_generation) | Uçtan uca temel RAG uygulaması | Web sayfası yükleme (`WebBaseLoader`), metin bölme (text splitting), retriever + LLM zinciri |
| [`05_advanced_chatbot_example`](./05_advanced_chatbot_example) | OpenAI Assistants API ile gelişmiş chatbot | Flask API, custom fonksiyon çağırma (function calling), Airtable entegrasyonu, sunucuya deploy |
| [`06_agent_concept_and_react_technique`](./06_agent_concept_and_react_technique) | Agent kavramı ve ReAct tekniği | Tavily arama aracı, LangGraph ile agent oluşturma, agent hafızası |
| [`07_react_agent_deep_dive`](./07_react_agent_deep_dive) | ReAct agent'a derinlemesine bakış | Mesaj ekleme ve state yönetimi |
| [`08_advanced_rag_with_langgraph`](./08_advanced_rag_with_langgraph) | LangGraph ile ileri seviye, kendini düzelten RAG | Routing, doküman değerlendirme (grading), halüsinasyon kontrolü, web araması ile fallback, graf görselleştirme |

## 🛠️ Kullanılan Teknolojiler

- **[LangChain](https://github.com/langchain-ai/langchain)** — LLM orkestrasyonu (chains, prompts, retrievers)
- **[LangGraph](https://github.com/langchain-ai/langgraph)** — Node/edge tabanlı, durum (state) yönetimli agent ve RAG akışları
- **[LangSmith](https://smith.langchain.com/)** — Zincirlerin/agent'ların izlenmesi (tracing), debug ve prompt yönetimi
- **OpenAI API** (`gpt-3.5-turbo`, embeddings, Assistants API)
- **Chroma / FAISS** — Vektör veritabanları
- **Tavily** — Agent'lar için web arama aracı
- **FastAPI + LangServe** — Chain'leri API olarak yayınlama
- **Flask** — OpenAI Assistants API tabanlı chatbot servisi

## 🚀 Kurulum

Her modül bağımsız olduğu için kurulumu ilgili klasörün içinde yapmanız gerekir.

```bash
# 1. Repoyu klonlayın
git clone https://github.com/Rasittekin18/ai-applications-langchain-rag.git
cd ai-applications-langchain-rag

# 2. İlgili modülün klasörüne girin (örnek)
cd 08_advanced_rag_with_langgraph

# 3. Sanal ortam oluşturun ve aktive edin
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 4. Bağımlılıkları yükleyin
pip install -r requirements.txt

# 5. .env dosyanızı oluşturun (aşağıdaki bölüme bakın)

# 6. Uygulamayı çalıştırın
python main.py
```

> **Not:** Python **3.9+** (tercihen 3.10 veya üzeri) kullanılması önerilir.

## 🔑 Ortam Değişkenleri (.env)

Her modülün kendi `.env` dosyası olmalıdır (bkz. ilgili klasördeki `README.md`). Genel olarak ihtiyaç duyulan değişkenler:

```env
OPENAI_API_KEY=

LANGCHAIN_API_KEY=
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=

TAVILY_API_KEY=
```

- `OPENAI_API_KEY`: [OpenAI Platform](https://platform.openai.com/) üzerinden alınır.
- `LANGCHAIN_API_KEY` / `LANGCHAIN_TRACING_V2` / `LANGCHAIN_PROJECT`: LangSmith ile izleme (tracing) için kullanılır, isteğe bağlıdır ancak önerilir.
- `TAVILY_API_KEY`: Agent ve web araması içeren modüllerde ([Tavily](https://tavily.com/)) gereklidir.
- `05_advanced_chatbot_example` klasöründe ek olarak `AIRTABLE_API_KEY` gerekir.

## 🧠 `08_advanced_rag_with_langgraph` — Öne Çıkan Modül

Bu proje, LangGraph kullanılarak kurulmuş, klasik RAG'in ötesine geçen **kendini düzelten (corrective) bir RAG akışı** içerir:

1. **Route Question** — Soru; vektör store'a mı yoksa web aramasına mı yönlendirilecek, karar verilir.
2. **Retrieve** — Vektör store'dan (Chroma) ilgili dokümanlar çekilir.
3. **Grade Documents** — Getirilen dokümanların soruyla alakalı olup olmadığı değerlendirilir.
4. **Web Search (fallback)** — Dokümanlar yetersizse veya alakasızsa Tavily ile web araması yapılır.
5. **Generate** — LLM, elde edilen bağlamla yanıtı üretir.
6. **Hallucination & Answer Grading** — Üretilen yanıtın dokümanlara dayanıp dayanmadığı (halüsinasyon kontrolü) ve kullanıcının sorusunu gerçekten yanıtlayıp yanıtlamadığı kontrol edilir; gerekirse yeniden üretim veya web aramasına dönülür.

Akışın görsel şeması `08_advanced_rag_with_langgraph/graph.png` dosyasında bulunmaktadır; kod ise `graph/` klasörü altında `nodes/` (node fonksiyonları), `chains/` (router, grader, generation zincirleri) ve `state.py` (graf state tanımı) olarak organize edilmiştir.

## 📖 Kaynaklar

- [LangChain Dokümantasyonu](https://python.langchain.com/)
- [LangGraph Dokümantasyonu](https://langchain-ai.github.io/langgraph/)
- [LangSmith](https://smith.langchain.com/)


