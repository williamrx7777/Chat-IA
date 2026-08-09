import streamlit as st
import os
import tempfile
from google import genai
from google.genai import types

# -------------------------------------------------------------------
# Configuração Inicial da Página
# -------------------------------------------------------------------
st.set_page_config(page_title="Gemini IA Chat", page_icon="🧠", layout="wide")
st.title("🧠 Gemini IA Chat com Streamlit")

# Inicializa o cliente da nova SDK
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    st.error("⚠️ Defina a variável de ambiente GOOGLE_API_KEY com sua chave do AI Studio.")
    st.stop()

client = genai.Client(api_key=api_key)

# -------------------------------------------------------------------
# Gerenciamento de Estado (Session State)
# -------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_gemini_files" not in st.session_state:
    st.session_state.uploaded_gemini_files = {}

# -------------------------------------------------------------------
# Barra Lateral (Sidebar) - Configurações e Anexos
# -------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configurações")
    
    # 1. Opção de Pensamento Profundo
    use_thinking = st.toggle("Habilitar Pensamento Profundo", value=False, 
                             help="Usa o modelo gemini-2.0-flash-thinking-exp para raciocínio complexo.")
    
    # 2. Opção de Busca na Internet
    use_search = st.toggle("Habilitar Busca na Web", value=False,
                           help="Permite que a IA pesquise no Google para informações atualizadas.")
    
    st.divider()
    
    # 3. Anexo de Arquivos (File API)
    st.header("📎 Anexar Arquivo")
    uploaded_file = st.file_uploader("Faça upload para análise", type=["pdf", "txt", "png", "jpg", "jpeg", "csv"])
    
    if st.button("Limpar Histórico"):
        st.session_state.messages = []
        st.rerun()

# Define qual modelo usar com base na escolha do usuário
MODEL_ID = "gemini-2.0-flash-thinking-exp-01-21" if use_thinking else "gemini-2.5-flash"

# -------------------------------------------------------------------
# Exibição do Histórico de Chat
# -------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# -------------------------------------------------------------------
# Lógica Principal do Chat
# -------------------------------------------------------------------
if prompt := st.chat_input("Digite sua mensagem aqui..."):
    
    # Exibe a mensagem do usuário
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Prepara o conteúdo para enviar à API
    contents_to_send = []
    
    # Se houver um arquivo no uploader, fazemos o upload via File API
    if uploaded_file is not None:
        file_hash = hash(uploaded_file.getvalue())
        
        # Evita re-upar o mesmo arquivo repetidamente na mesma sessão
        if file_hash not in st.session_state.uploaded_gemini_files:
            with st.spinner("Fazendo upload do arquivo para o Gemini..."):
                # Salva temporariamente para a SDK poder ler
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                
                # Upload usando a File API da nova SDK
                gemini_file = client.files.upload(file=tmp_path, display_name=uploaded_file.name)
                st.session_state.uploaded_gemini_files[file_hash] = gemini_file
                os.remove(tmp_path) # Limpa o arquivo temporário local
        
        # Adiciona a referência do arquivo no conteúdo do prompt
        contents_to_send.append(st.session_state.uploaded_gemini_files[file_hash])

    # Adiciona o texto do usuário
    contents_to_send.append(prompt)

    # Configurações de Geração (Ferramentas)
    tools = []
    if use_search:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
        
    config = types.GenerateContentConfig(
        tools=tools if tools else None,
        temperature=0.7 if not use_thinking else None # Modelos de pensamento controlam a própria temperatura
    )

    # Prepara o histórico no formato exigido pela SDK (opcional, dependendo de como quer gerenciar contexto)
    # Aqui estamos enviando o histórico formatado
    formatted_history = []
    for m in st.session_state.messages[:-1]: # Exclui a mensagem atual que já está em contents_to_send
        role = "user" if m["role"] == "user" else "model"
        formatted_history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=m["content"])])
        )
    
    # Adiciona a mensagem atual ao histórico que será enviado
    # A SDK aceita listas mistas de texto e arquivos na chamada principal
    current_content = types.Content(
        role="user", 
        parts=[
            types.Part.from_text(text=prompt) if isinstance(item, str) 
            else types.Part.from_uri(file_uri=item.uri, mime_type=item.mime_type) 
            for item in contents_to_send
        ]
    )
    formatted_history.append(current_content)

    # Gera a resposta
    with st.chat_message("model"):
        with st.spinner("Processando..." if not use_thinking else "Pensando profundamente..."):
            try:
                response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=formatted_history,
                    config=config
                )
                
                resposta_texto = response.text
                
                # Se o modelo usou pensamento profundo, a SDK retorna as "parts" de pensamento separadas
                # (Dependendo da versão exata da SDK, o pensamento pode vir no texto ou em partes específicas)
                # Vamos renderizar a resposta final de forma limpa
                st.markdown(resposta_texto)
                st.session_state.messages.append({"role": "model", "content": resposta_texto})
                
            except Exception as e:
                st.error(f"Erro na API do Gemini: {e}")