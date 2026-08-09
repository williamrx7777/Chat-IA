import streamlit as st
import os
import tempfile
import base64
import io
import wave
import re
from google import genai
from google.genai import types

# -------------------------------------------------------------------
# Configuração Inicial da Página
# -------------------------------------------------------------------
st.set_page_config(page_title="Gemini IA Chat", page_icon="🧠", layout="wide")
st.title("🧠 Gemini IA Chat Multimodal & Voz")

# Inicializa o cliente da nova SDK
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    st.error("⚠️ Defina a variável de ambiente GOOGLE_API_KEY com sua chave do AI Studio.")
    st.stop()

client = genai.Client(api_key=api_key)

# -------------------------------------------------------------------
# Funções Auxiliares de Áudio
# -------------------------------------------------------------------
def pcm_to_wav_bytes(pcm_bytes, channels=1, rate=24000, sample_width=2):
    """Converte o áudio PCM bruto retornado pela API em formato WAV legível pelo navegador."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)
    return buffer.getvalue()

def gerar_audio_resposta(texto):
    """Tenta gerar o áudio TTS da resposta. Retorna None se o serviço estiver indisponível."""
    try:
        # Limpa marcações Markdown do texto para melhorar a sintetização de voz
        texto_limpo = re.sub(r"[\*\#\`\_]", "", texto).strip()
        if not texto_limpo:
            return None

        interaction = client.interactions.create(
            model="gemini-3.1-flash-tts-preview",
            input=texto_limpo,
            response_format={"type": "audio"},
            generation_config={
                "speech_config": [{"voice": "Leda"}]
            }
        )
        raw_pcm_bytes = base64.b64decode(interaction.output_audio.data)
        return pcm_to_wav_bytes(raw_pcm_bytes)
    except Exception as e:
        print(f"Erro no serviço de TTS: {e}")
        return None

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
    
    use_thinking = st.toggle("Habilitar Pensamento Profundo", value=False, 
                             help="Usa o modelo gemini-3.5-flash para raciocínio complexo.")
    
    use_search = st.toggle("Habilitar Busca na Web", value=False,
                           help="Permite que a IA pesquise no Google para informações atualizadas.")
    
    enable_voice_response = st.toggle("Habilitar Resposta por Voz", value=True,
                                      help="Tenta reproduzir a resposta em áudio quando disponível.")
    
    st.divider()
    
    st.header("🎙️ Entrada por Voz")
    voice_input = st.audio_input("Grave sua pergunta por voz")
    
    st.divider()
    
    st.header("📎 Anexar Arquivo")
    uploaded_file = st.file_uploader("Faça upload para análise", type=["pdf", "txt", "png", "jpg", "jpeg", "csv"])
    
    if st.button("Limpar Histórico"):
        st.session_state.messages = []
        st.rerun()

MODEL_ID = "gemini-3.5-flash" if use_thinking else "gemini-2.5-flash"

# -------------------------------------------------------------------
# Exibição do Histórico de Chat
# -------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "audio" in msg and msg["audio"]:
            st.audio(msg["audio"], format="audio/wav")

# -------------------------------------------------------------------
# Lógica Principal do Chat
# -------------------------------------------------------------------
text_prompt = st.chat_input("Digite sua mensagem aqui...")

# Define se a entrada veio por texto ou por voz
prompt = None
audio_prompt_file = None

if text_prompt:
    prompt = text_prompt
elif voice_input is not None:
    prompt = "🎙️ [Mensagem enviada por áudio]"
    audio_prompt_file = voice_input

if prompt:
    # Exibe a mensagem do usuário no chat
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        if audio_prompt_file:
            st.audio(audio_prompt_file)

    contents_to_send = []

    # 1. Processa arquivo anexado via Upload
    if uploaded_file is not None:
        file_hash = hash(uploaded_file.getvalue())
        if file_hash not in st.session_state.uploaded_gemini_files:
            with st.spinner("Enviando arquivo anexado..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                
                # Ajustado para usar config para o display_name
                gemini_file = client.files.upload(
                    file=tmp_path, 
                    config=types.UploadFileConfig(display_name=uploaded_file.name)
                )
                st.session_state.uploaded_gemini_files[file_hash] = gemini_file
                os.remove(tmp_path)
        contents_to_send.append(st.session_state.uploaded_gemini_files[file_hash])

    # 2. Processa o áudio gravado do usuário via Entrada por Voz
    if audio_prompt_file is not None:
        with st.spinner("Processando áudio de entrada..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                tmp.write(audio_prompt_file.getvalue())
                tmp_audio_path = tmp.name
            
            # Removido mime_type= (a SDK detecta o tipo automaticamente pela extensão .wav)
            audio_gemini_file = client.files.upload(file=tmp_audio_path)
            contents_to_send.append(audio_gemini_file)
            os.remove(tmp_audio_path)
    else:
        contents_to_send.append(prompt)

    # Configuração de ferramentas
    tools = []
    if use_search:
        tools.append(types.Tool(google_search=types.GoogleSearch()))
        
    config = types.GenerateContentConfig(
        tools=tools if tools else None,
        temperature=0.7 if not use_thinking else None
    )

    # Monta histórico de conversa
    formatted_history = []
    for m in st.session_state.messages[:-1]:
        role = "user" if m["role"] == "user" else "model"
        formatted_history.append(
            types.Content(role=role, parts=[types.Part.from_text(text=m["content"])])
        )
    
    current_content = types.Content(
        role="user", 
        parts=[
            types.Part.from_text(text=item) if isinstance(item, str) 
            else types.Part.from_uri(file_uri=item.uri, mime_type=item.mime_type) 
            for item in contents_to_send
        ]
    )
    formatted_history.append(current_content)

    # Gera a resposta do modelo
    with st.chat_message("model"):
        with st.spinner("Processando resposta..."):
            try:
                response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=formatted_history,
                    config=config
                )
                
                resposta_texto = response.text
                audio_bytes = None
                
                # Exibe resposta em texto
                st.markdown(resposta_texto)

                # Tenta gerar resposta em áudio (se habilitado)
                if enable_voice_response:
                    with st.spinner("Gerando resposta em voz..."):
                        audio_bytes = gerar_audio_resposta(resposta_texto)
                        if audio_bytes:
                            st.audio(audio_bytes, format="audio/wav")
                        else:
                            st.warning("⚠️ O serviço de voz está indisponível no momento. Exibindo apenas a resposta em texto.")

                st.session_state.messages.append({
                    "role": "model", 
                    "content": resposta_texto,
                    "audio": audio_bytes
                })
                
            except Exception as e:
                st.error(f"Erro na API do Gemini: {e}")