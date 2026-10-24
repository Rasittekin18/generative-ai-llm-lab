
from langchain_community.embeddings import HuggingFaceBgeEmbeddings
from langchain_community.llms import HuggingFacePipeline
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain_community.document_loaders import PubMedLoader
from langchain_community.document_loaders import HuggingFaceDatasetLoader
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM,pipeline
import os
from langchain_community.llms import HuggingFaceEndpoint
from langchain.text_splitter import TokenTextSplitter,CharacterTextSplitter

def rag_func():
#PubmedLoader ile Pubmed'den istenilen konudaki dokümanların yüklenmesi
#Programın çalışma süresinin uzamaması ve performans sorunu yaşanmaması için 7 doküman yükleniyor.
#Bu parametre büyük tutularak daha fazla sayıda doküman yüklenebilir.
    query1=input("Lütfen soru sormak istediğiniz konuyu giriniz?")
    loader = PubMedLoader(query= query1,load_max_docs=7)
    data = loader.load()

    #Yüklenen verinin daha küçük parçalara (chunk'lara) bölünmesi
    #Her bir chunk 140 karakter ve chunk'lar arası 50 karakterlik kesişim (overlap) tanımlanıyor.
    text_splitter = TokenTextSplitter(chunk_size=140, chunk_overlap=50)
    chunks = text_splitter.split_documents(data)

    #Verinin anlam ifade etmesi ve birbiri ile ilişkilendirilmesi için kelime gömme (embeddings) ile ifade edilmesi gerekiyor.
    #Token'ların Kelime gömmelere çevrilmesi için kullanılacak embeddings tanımlanıyor.
    huggingface_embeddings = HuggingFaceBgeEmbeddings(
        model_name="sentence-transformers/all-MiniLM-l6-v2",
        model_kwargs={'device':'cpu'},
        encode_kwargs={'normalize_embeddings': True}
    )

    #Daha önce oluşturulan chunk'lar kelime gömmelere (embeddings) dönüştürülerek vektör veritabanına yazılıyor
    #Kelimelerin vektörel olarak tutulacağı vektör veritabanı olarak FAISS kullanılıyor
    vectorstore = FAISS.from_documents(chunks, huggingface_embeddings)
    #Soru ile RAG sistemine sorulacak soru tanımlanıyor
    #vectorstore.similarity_search fonksiyonu ile vektör store'dan bu soru ile ilişkili olabilecek dökümanlar bulunuyor.

    devam = True
    while devam:
        soru = input("Lütfen sormak istediğiniz soruyu giriniz?")
        if (soru == "E"):
            print("Programdan çıkmak istediniz.")
            break


        relevant_documents = vectorstore.similarity_search(soru)
        retriever = vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 3})
        #Huggingface token'ın yüklenmesi, burada kendi token'ınızı girmelisiniz.

        HUGGINGFACEHUB_API_TOKEN = 'xxx'

        os.environ["HUGGINGFACEHUB_API_TOKEN"] = HUGGINGFACEHUB_API_TOKEN

        import warnings
        warnings.filterwarnings("ignore")

        #Huggingface hubdan kullanılacak modelin tanımlanması
        model_ismi = "mistralai/Mistral-7B-Instruct-v0.2"

        #llm'in Huggingface hub üzerinden kullanılması
        llm1 = HuggingFaceEndpoint(
            repo_id=model_ismi,
            temperature = 0.5,
            model_kwargs={"max_length": 610,"token": HUGGINGFACEHUB_API_TOKEN}
        )

        #İstemin (prompt) oluşturulması
        #prompt içinde context ve question değişken olarak tanımlanıyor.
        #Context, retriever sistemi tarafından sağlanacak.
        #Question olarak daha önce query olarak tanımladığımız soru verilecek.
        prompt_template = """Use the following pieces of context to answer the question at the end. Please follow the following rule:
        1. If you find the answer, write the answer in a concise way at least with two sentences.
        {context}
        Question: {question}
        Helpful Answer:
        """
        PROMPT = PromptTemplate(
         template=prompt_template, input_variables=["context", "soru"]
        )

        #RetrievalQA chainin oluşturulması
        retrievalQA = RetrievalQA.from_chain_type(
            llm=llm1,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": PROMPT}
        )

        #Sorunun RAG tarafından cevaplanması
        result = retrievalQA.invoke({"query": soru},max_new_tokens=1000)
        print("RAG tarafından üretilen cevap:\n", result["result"])
        print("Soruyu cevaplamak için kullanılan kaynaklar:\n")
        for i in range(len(relevant_documents)):
            print(relevant_documents[i].metadata)

if __name__ == "__main__":
    rag_func()