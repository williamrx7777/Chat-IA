import streamlit as st
import os
import tempfile
import base64
import io
import wave
import re
import time
import pandas as pd
import uuid
from supabase import create_client, Client
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------------------------
# Configuração Inicial da Página
# -------------------------------------------------------------------
st.set_page_config(page_title="Gemini IA Chat & Portal Petronect (Paola)", page_icon="🧠", layout="wide")
st.title("🧠 Gemini IA Chat & Portal Petronect (Paola)")

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    st.error("⚠️ Defina a variável de ambiente GOOGLE_API_KEY com sua chave do AI Studio.")
    st.stop()

client = genai.Client(api_key=api_key)

# -------------------------------------------------------------------
# Configuração do Supabase
# -------------------------------------------------------------------
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

supabase = None
if supabase_url and supabase_key:
    try:
        supabase = create_client(supabase_url, supabase_key)
    except Exception as e:
        st.error(f"Erro ao inicializar o cliente Supabase: {e}")
else:
    st.sidebar.error("⚠️ Credenciais do Supabase ausentes no .env")

# -------------------------------------------------------------------
# Funções de Banco de Dados (Supabase)
# -------------------------------------------------------------------
def criar_nova_conversa(titulo="Nova conversa", tipo="GERAL"):
    novo_ukey = str(uuid.uuid4())
    if supabase:
        try:
            supabase.table("conversas_v2").insert({
                "ukey": novo_ukey, 
                "titulo": titulo, 
                "tipo": tipo
            }).execute()
        except Exception as e:
            st.toast(f"Erro ao criar conversa no Supabase: {e}", icon="❌")
    return novo_ukey

def listar_conversas(tipo=None):
    conversas = []
    if supabase:
        try:
            if tipo:
                response = supabase.table("conversas_v2").select("ukey, titulo, tipo").eq("tipo", tipo).order("data_criacao", desc=True).execute()
            else:
                response = supabase.table("conversas_v2").select("ukey, titulo, tipo").order("data_criacao", desc=True).execute()
            
            for row in response.data:
                conversas.append((row["ukey"], row["titulo"], row.get("tipo", "GERAL")))
        except Exception as e:
            st.toast(f"Erro ao listar conversas: {e}", icon="❌")
    return conversas

def carregar_mensagens(conversa_ukey):
    mensagens = []
    if supabase:
        try:
            response = supabase.table("historicochat_v2").select("papel, mensagem").eq("conversa_ukey", conversa_ukey).order("id", desc=False).execute()
            for row in response.data:
                mensagens.append({"role": row["papel"], "content": row["mensagem"]})
        except Exception as e:
            st.toast(f"Erro ao carregar mensagens: {e}", icon="❌")
    return mensagens

def salvar_mensagem_banco(conversa_ukey, papel, mensagem):
    if supabase:
        try:
            supabase.table("historicochat_v2").insert({
                "conversa_ukey": conversa_ukey, 
                "papel": papel, 
                "mensagem": str(mensagem)
            }).execute()
        except Exception as e:
            st.toast(f"Erro ao salvar mensagem: {e}", icon="❌")

def atualizar_titulo_conversa(conversa_ukey, novo_titulo):
    if supabase:
        try:
            supabase.table("conversas_v2").update({
                "titulo": novo_titulo[:45]
            }).eq("ukey", conversa_ukey).execute()
        except Exception as e:
            st.toast(f"Erro ao atualizar título: {e}", icon="❌")

def deletar_conversa(conversa_ukey):
    if supabase:
        try:
            supabase.table("historicochat_v2").delete().eq("conversa_ukey", conversa_ukey).execute()
            supabase.table("conversas_v2").delete().eq("ukey", conversa_ukey).execute()
        except Exception as e:
            st.toast(f"Erro ao deletar conversa: {e}", icon="❌")

# -------------------------------------------------------------------
# Gerenciamento de Estado (Session State)
# -------------------------------------------------------------------
if "conversa_ativa_ukey" not in st.session_state:
    st.session_state.conversa_ativa_ukey = None
if "messages" not in st.session_state:
    st.session_state.messages = []

if "conversa_dados_ukey" not in st.session_state:
    st.session_state.conversa_dados_ukey = None
if "messages_dados" not in st.session_state:
    st.session_state.messages_dados = []

if "conversa_paola_ukey" not in st.session_state:
    st.session_state.conversa_paola_ukey = None
if "messages_paola" not in st.session_state:
    st.session_state.messages_paola = []

if "uploaded_gemini_files" not in st.session_state:
    st.session_state.uploaded_gemini_files = {}

if "key_audio_geral" not in st.session_state:
    st.session_state.key_audio_geral = str(uuid.uuid4())
if "key_uploader_dados" not in st.session_state:
    st.session_state.key_uploader_dados = str(uuid.uuid4())
if "key_uploader_paola" not in st.session_state:
    st.session_state.key_uploader_paola = str(uuid.uuid4())

# -------------------------------------------------------------------
# Funções Auxiliares - Áudio e Normalização de Datas
# -------------------------------------------------------------------
def pcm_to_wav_bytes(pcm_bytes, channels=1, rate=24000, sample_width=2):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)
    return buffer.getvalue()

def gerar_audio_resposta(texto):
    try:
        texto_limpo = re.sub(r"[\*\#\`\_]", "", texto).strip()
        if not texto_limpo:
            return None
        interaction = client.interactions.create(
            model="gemini-3.1-flash-tts-preview",
            input=texto_limpo,
            response_format={"type": "audio"},
            generation_config={"speech_config": [{"voice": "Leda"}]}
        )
        raw_pcm_bytes = base64.b64decode(interaction.output_audio.data)
        return pcm_to_wav_bytes(raw_pcm_bytes)
    except Exception:
        return None

def padronizar_colunas_data(df):
    """Identifica e padroniza as colunas de Ano e Mês para nomes textuais padrão."""
    cols_lower = {str(c).strip().lower(): c for c in df.columns}
    
    col_ano = cols_lower.get('ano') or cols_lower.get('anos') or cols_lower.get('exercicio')
    col_mes = cols_lower.get('mes') or cols_lower.get('mês') or cols_lower.get('mes_n')
    col_periodo = cols_lower.get('periodo') or cols_lower.get('período') or cols_lower.get('data')

    # Se não houver coluna de Ano explícita, tenta extrair de 'PERIODO' ou 'DATA'
    if not col_ano and col_periodo:
        try:
            series_str = df[col_periodo].astype(str)
            # Tenta pegar 4 dígitos do ano (ex: 202205 -> 2022)
            anos_extraidos = series_str.str.extract(r'(\b20\d{2}\b)')[0]
            if anos_extraidos.notna().any():
                df['ANO_EXTRAIDO'] = pd.to_numeric(anos_extraidos, errors='coerce').fillna(0).astype(int)
                col_ano = 'ANO_EXTRAIDO'
        except Exception:
            pass

    # Normalização do ANO para INT
    if col_ano and col_ano in df.columns:
        df[col_ano] = pd.to_numeric(df[col_ano], errors='coerce').fillna(0).astype(int)

    # Normalização do MÊS para Texto ("Janeiro", "Maio", etc.)
    if col_mes and col_mes in df.columns:
        mapa_meses = {
            1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
            5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
            9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
            "1": "Janeiro", "01": "Janeiro", "2": "Fevereiro", "02": "Fevereiro",
            "3": "Março", "03": "Março", "4": "Abril", "04": "Abril",
            "5": "Maio", "05": "Maio", "6": "Junho", "06": "Junho",
            "7": "Julho", "07": "Julho", "8": "Agosto", "08": "Agosto",
            "9": "Setembro", "09": "Setembro", "10": "Outubro",
            "11": "Novembro", "12": "Dezembro",
            "JAN": "Janeiro", "FEV": "Fevereiro", "MAR": "Março", "ABR": "Abril",
            "MAI": "Maio", "JUN": "Junho", "JUL": "Julho", "AGO": "Agosto",
            "SET": "Setembro", "OUT": "Outubro", "NOV": "Novembro", "DEZ": "Dezembro",
            "JANEIRO": "Janeiro", "FEVEREIRO": "Fevereiro", "MARÇO": "Março", "MARCO": "Março",
            "ABRIL": "Abril", "MAIO": "Maio", "JUNHO": "Junho", "JULHO": "Julho",
            "AGOSTO": "Agosto", "SETEMBRO": "Setembro", "OUTUBRO": "Outubro",
            "NOVEMBRO": "Novembro", "DEZEMBRO": "Dezembro"
        }

        def converter_mes(val):
            if pd.isna(val):
                return "Outros"
            try:
                val_num = int(float(val))
                if val_num in mapa_meses:
                    return mapa_meses[val_num]
            except (ValueError, TypeError):
                pass
            
            val_str = str(val).strip().upper()
            return mapa_meses.get(val_str, str(val).capitalize())

        df[col_mes] = df[col_mes].apply(converter_mes)

    return df, col_ano, col_mes

# -------------------------------------------------------------------
# Barra Lateral (Sidebar)
# -------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 💬 Histórico de Conversas")
    
    if st.button("✨ Nova Conversa / Análise", use_container_width=True):
        st.session_state.conversa_ativa_ukey = None
        st.session_state.messages = []
        st.session_state.conversa_dados_ukey = None
        st.session_state.messages_dados = []
        st.session_state.conversa_paola_ukey = None
        st.session_state.messages_paola = []
        st.session_state.uploaded_gemini_files = {}
        st.session_state.key_audio_geral = str(uuid.uuid4())
        st.session_state.key_uploader_dados = str(uuid.uuid4())
        st.session_state.key_uploader_paola = str(uuid.uuid4())
        st.rerun()

    lista_chats = listar_conversas()
    if lista_chats:
        icones_tipo = {"GERAL": "💬", "DADOS": "📊", "PAOLA": "📑"}
        for item in lista_chats:
            ukey, titulo, tipo_chat = item[0], item[1], item[2] if len(item) > 2 else "GERAL"
            icone = icones_tipo.get(tipo_chat, "💬")
            
            col_titulo, col_del = st.columns([0.82, 0.18])
            with col_titulo:
                if tipo_chat == "DADOS":
                    is_active = (ukey == st.session_state.get("conversa_dados_ukey"))
                elif tipo_chat == "PAOLA":
                    is_active = (ukey == st.session_state.get("conversa_paola_ukey"))
                else:
                    is_active = (ukey == st.session_state.get("conversa_ativa_ukey"))
                    
                prefixo = "▶ " if is_active else "  "
                label_btn = f"{prefixo}{icone} {titulo}"
                
                if st.button(label_btn[:30], key=f"chat_btn_{ukey}", use_container_width=True):
                    if tipo_chat == "DADOS":
                        st.session_state.conversa_dados_ukey = ukey
                        st.session_state.messages_dados = carregar_mensagens(ukey)
                        st.session_state.key_uploader_dados = str(uuid.uuid4())
                    elif tipo_chat == "PAOLA":
                        st.session_state.conversa_paola_ukey = ukey
                        st.session_state.messages_paola = carregar_mensagens(ukey)
                        st.session_state.key_uploader_paola = str(uuid.uuid4())
                    else:
                        st.session_state.conversa_ativa_ukey = ukey
                        st.session_state.messages = carregar_mensagens(ukey)
                        st.session_state.key_audio_geral = str(uuid.uuid4())
                    st.rerun()
                    
            with col_del:
                if st.button("🗑️", key=f"del_btn_{ukey}", help="Excluir esta conversa"):
                    if st.session_state.get("conversa_ativa_ukey") == ukey:
                        st.session_state.conversa_ativa_ukey = None
                        st.session_state.messages = []
                    if st.session_state.get("conversa_dados_ukey") == ukey:
                        st.session_state.conversa_dados_ukey = None
                        st.session_state.messages_dados = []
                    if st.session_state.get("conversa_paola_ukey") == ukey:
                        st.session_state.conversa_paola_ukey = None
                        st.session_state.messages_paola = []
                        
                    deletar_conversa(ukey)
                    st.rerun()

    st.divider()
    st.header("⚙️ Configurações IA")
    use_thinking = st.toggle("Habilitar Pensamento Profundo", value=False)
    use_search = st.toggle("Habilitar Busca na Web", value=False)
    enable_voice_response = st.toggle("Habilitar Resposta por Voz", value=False)
    
    st.divider()
    st.header("🎙️ Entrada por Voz")
    voice_input = st.audio_input("Grave sua pergunta", key=st.session_state.key_audio_geral)

MODEL_ID = "gemini-3.5-flash-lite" if use_thinking else "gemini-2.5-flash"

# -------------------------------------------------------------------
# Interface Principal em Abas (Tabs)
# -------------------------------------------------------------------
tab_chat, tab_dados, tab_paola = st.tabs([
    "💬 Chat Geral com IA", 
    "📊 Análise de Dados & Chat", 
    "💬 Paola - Petronect (Editais)"
])

# ===================================================================
# ABA 1: CHAT GERAL COM IA
# ===================================================================
with tab_chat:
    if not st.session_state.conversa_ativa_ukey and not st.session_state.messages:
        st.info("💡 Inicie uma nova conversa digitando abaixo ou selecionando um histórico na barra lateral.")

    arquivo_audio = st.file_uploader(
        "📎 Anexar arquivo de áudio para transcrição (.mp3, .wav, .m4a, .ogg)", 
        type=["mp3", "wav", "m4a", "ogg"],
        key="uploader_audio_chat"
    )

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    text_prompt = st.chat_input("Pergunte algo à IA...")
    prompt = None
    audio_para_processar = None
    mime_audio = None

    if text_prompt:
        prompt = text_prompt
    elif voice_input is not None:
        prompt = "🎙️ [Áudio gravado via microfone]"
        audio_para_processar = voice_input.getvalue()
        mime_audio = voice_input.type if voice_input.type else "audio/wav"
    elif arquivo_audio is not None and "audio_enviado" not in st.session_state:
        prompt = f"🎵 [Arquivo de áudio enviado: {arquivo_audio.name}]"
        audio_para_processar = arquivo_audio.getvalue()
        mime_audio = arquivo_audio.type if arquivo_audio.type else "audio/mp3"
        st.session_state.audio_enviado = True

    if prompt:
        if not st.session_state.conversa_ativa_ukey:
            st.session_state.conversa_ativa_ukey = criar_nova_conversa(prompt[:45], tipo="GERAL")
        elif len(st.session_state.messages) == 0:
            atualizar_titulo_conversa(st.session_state.conversa_ativa_ukey, prompt)

        st.session_state.messages.append({"role": "user", "content": prompt})
        salvar_mensagem_banco(st.session_state.conversa_ativa_ukey, "user", prompt)
        
        with st.chat_message("user"):
            st.markdown(prompt)

        contents_to_send = []
        
        if audio_para_processar:
            with st.spinner("🎧 Transcrevendo e processando o áudio..."):
                extensao = mime_audio.split('/')[-1] if '/' in mime_audio else 'wav'
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{extensao}") as tmp:
                    tmp.write(audio_para_processar)
                    tmp_audio_path = tmp.name
                
                audio_gemini_file = client.files.upload(
                    file=tmp_audio_path,
                    config=types.UploadFileConfig(mime_type=mime_audio)
                )
                
                while audio_gemini_file.state.name == "PROCESSING":
                    time.sleep(1)
                    audio_gemini_file = client.files.get(name=audio_gemini_file.name)
                    
                contents_to_send.append(audio_gemini_file)
                contents_to_send.append("Por favor, faça a transcrição e responda ao áudio.")
                os.remove(tmp_audio_path)
        else:
            contents_to_send.append(prompt)

        tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
        config = types.GenerateContentConfig(tools=tools, temperature=0.7)

        formatted_history = []
        for m in st.session_state.messages[:-1]:
            role = "user" if m["role"] == "user" else "model"
            formatted_history.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        
        partes = []
        for item in contents_to_send:
            if isinstance(item, str):
                partes.append(types.Part.from_text(text=item))
            else:
                partes.append(types.Part.from_uri(file_uri=item.uri, mime_type=item.mime_type))

        current_content = types.Content(role="user", parts=partes)
        formatted_history.append(current_content)

        with st.chat_message("model"):
            with st.spinner("Pensando..."):
                try:
                    response = client.models.generate_content(model=MODEL_ID, contents=formatted_history, config=config)
                    resposta_texto = response.text
                    st.markdown(resposta_texto)

                    if enable_voice_response:
                        with st.spinner("Gerando voz..."):
                            audio_bytes = gerar_audio_resposta(resposta_texto)
                            if audio_bytes:
                                st.audio(audio_bytes, format="audio/wav")

                    st.session_state.messages.append({"role": "model", "content": resposta_texto})
                    salvar_mensagem_banco(st.session_state.conversa_ativa_ukey, "model", resposta_texto)
                except Exception as e:
                    st.error(f"Erro na API do Gemini: {e}")

# ===================================================================
# ABA 2: ANÁLISE DE DADOS & CHAT INTERATIVO (CORRIGIDO)
# ===================================================================
with tab_dados:
    st.markdown("### 📊 Análise de Dados & Chat Interativo")
    
    arquivo_dados = st.file_uploader(
        "Selecione a base de dados (.csv, .xlsx, .xls)", 
        type=["csv", "xlsx", "xls"], 
        key=st.session_state.key_uploader_dados
    )
    
    if arquivo_dados:
        try:
            arquivo_dados.seek(0)
            if arquivo_dados.name.endswith('.csv'):
                try:
                    df = pd.read_csv(arquivo_dados, sep=None, engine='python', encoding='utf-8')
                except Exception:
                    arquivo_dados.seek(0)
                    df = pd.read_csv(arquivo_dados, sep=';', encoding='latin1')
            else:
                df = pd.read_excel(arquivo_dados)

            # Padroniza Ano e Mês na planilha
            df, col_ano, col_mes = padronizar_colunas_data(df)

            # Extrai listas únicas disponíveis
            anos_disponiveis = sorted([int(a) for a in df[col_ano].dropna().unique() if a > 0]) if col_ano and col_ano in df.columns else []
            meses_ordem = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
            meses_na_base = [m for m in meses_ordem if m in df[col_mes].values] if col_mes and col_mes in df.columns else meses_ordem

            # Aplica pendências vindas de perguntas no chat
            if "pending_anos" in st.session_state:
                st.session_state.filtro_anos = st.session_state.pop("pending_anos")
            if "pending_meses" in st.session_state:
                st.session_state.filtro_meses = st.session_state.pop("pending_meses")

            # Inicializa Session State dos Seletores
            if 'filtro_anos' not in st.session_state:
                st.session_state.filtro_anos = anos_disponiveis
            if 'filtro_meses' not in st.session_state:
                st.session_state.filtro_meses = meses_na_base

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                anos_selecionados = st.multiselect("📅 Selecionar Ano(s):", options=anos_disponiveis, key="filtro_anos")
            with col_f2:
                meses_selecionados = st.multiselect("🗓️ Selecionar Mês(es):", options=meses_ordem, key="filtro_meses")

            # Aplicação Estrita dos Filtros
            df_filtrado = df.copy()
            if anos_selecionados and col_ano and col_ano in df_filtrado.columns:
                df_filtrado = df_filtrado[df_filtrado[col_ano].isin(anos_selecionados)]
            if meses_selecionados and col_mes and col_mes in df_filtrado.columns:
                df_filtrado = df_filtrado[df_filtrado[col_mes].isin(meses_selecionados)]

            with st.expander("👁️ Visualizar Dados Filtrados", expanded=False):
                st.write(f"**Registros exibidos:** {len(df_filtrado)} de {len(df)} linhas")
                st.dataframe(df_filtrado.head(15), use_container_width=True)

            if len(st.session_state.messages_dados) == 0:
                intro = f"Base `{arquivo_dados.name}` carregada com **{len(df)}** registros! Pergunte o que desejar."
                st.session_state.messages_dados.append({"role": "model", "content": intro})

            for msg in st.session_state.messages_dados:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            user_prompt_dados = st.chat_input("Ex: Compare 2022 x 2023 no mês de Maio...")

            # -----------------------------------------------------------------
            # Captura de Filtros na Pergunta e Atualização Visual
            # -----------------------------------------------------------------
            if user_prompt_dados:
                prompt_lower = user_prompt_dados.lower()
                
                anos_no_texto = [int(a) for a in re.findall(r'\b(20\d{2})\b', user_prompt_dados) if int(a) in anos_disponiveis]
                
                meses_map_busca = {
                    'janeiro': 'Janeiro', 'fevereiro': 'Fevereiro', 'março': 'Março', 'marco': 'Março',
                    'abril': 'Abril', 'maio': 'Maio', 'junho': 'Junho', 'julho': 'Julho',
                    'agosto': 'Agosto', 'setembro': 'Setembro', 'outubro': 'Outubro', 
                    'novembro': 'Novembro', 'dezembro': 'Dezembro'
                }
                meses_no_texto = [val for key, val in meses_map_busca.items() if key in prompt_lower and val in meses_ordem]

                filtros_alterados = False
                if anos_no_texto and set(anos_no_texto) != set(st.session_state.filtro_anos):
                    st.session_state.pending_anos = list(set(anos_no_texto))
                    filtros_alterados = True
                if meses_no_texto and set(meses_no_texto) != set(st.session_state.filtro_meses):
                    st.session_state.pending_meses = list(set(meses_no_texto))
                    filtros_alterados = True

                st.session_state.messages_dados.append({"role": "user", "content": user_prompt_dados})

                if filtros_alterados:
                    st.rerun()

            # -----------------------------------------------------------------
            # Execução da Análise com Gemini
            # -----------------------------------------------------------------
            if st.session_state.messages_dados and st.session_state.messages_dados[-1]["role"] == "user":
                prompt_atual = st.session_state.messages_dados[-1]["content"]

                df_filtrado_gemini = df.copy()
                if st.session_state.filtro_anos and col_ano and col_ano in df_filtrado_gemini.columns:
                    df_filtrado_gemini = df_filtrado_gemini[df_filtrado_gemini[col_ano].isin(st.session_state.filtro_anos)]
                if st.session_state.filtro_meses and col_mes and col_mes in df_filtrado_gemini.columns:
                    df_filtrado_gemini = df_filtrado_gemini[df_filtrado_gemini[col_mes].isin(st.session_state.filtro_meses)]

                # Amostragem inteligente se base for muito grande
                resumo_dados = df_filtrado_gemini.head(3000).to_csv(index=False)

                historico_api = []
                ultimo_role = None
                for m in st.session_state.messages_dados:
                    role = "user" if m["role"] == "user" else "model"
                    if role == ultimo_role:
                        continue
                    historico_api.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
                    ultimo_role = role

                prompt_com_contexto = (
                    f"Pergunta do Usuário: {prompt_atual}\n\n"
                    f"--- DADOS FILTRADOS DA PLANILHA PARA ANÁLISE ---\n"
                    f"{resumo_dados}"
                )
                historico_api[-1] = types.Content(role="user", parts=[types.Part.from_text(text=prompt_com_contexto)])

                system_instruction_dados = (
                    "Você é um analista financeiro e de dados especialista em negócios.\n"
                    "Analise os dados fornecidos na mensagem e responda à pergunta do usuário.\n"
                    "Faça comparações percentuais (crescimento/queda), monte tabelas comparativas limpas e traga destaques gerenciais."
                )

                with st.chat_message("model"):
                    with st.spinner("🤖 Analisando os dados filtrados..."):
                        try:
                            response_d = client.models.generate_content(
                                model=MODEL_ID, 
                                contents=historico_api, 
                                config=types.GenerateContentConfig(
                                    system_instruction=system_instruction_dados, 
                                    temperature=0.2
                                )
                            )
                            resp_texto_d = response_d.text
                            st.markdown(resp_texto_d)

                            st.session_state.messages_dados.append({"role": "model", "content": resp_texto_d})
                            if st.session_state.conversa_dados_ukey:
                                salvar_mensagem_banco(st.session_state.conversa_dados_ukey, "user", prompt_atual)
                                salvar_mensagem_banco(st.session_state.conversa_dados_ukey, "model", resp_texto_d)

                        except Exception as e:
                            st.error(f"Erro na API do Gemini: {e}")

        except Exception as erro:
            st.error(f"Erro ao processar a planilha: {erro}")
    else:
        st.info("💡 Faça o upload de uma planilha para habilitar os filtros e a análise interativa.")

# ===================================================================
# ABA 3: PAOLA - PETRONECT (EDITAIS E LICITAÇÕES)
# ===================================================================
with tab_paola:
    st.markdown("### 💬 Paola - Assistente Virtual de Editais (Petronect)")
    
    if not st.session_state.conversa_paola_ukey and not st.session_state.messages_paola:
        st.info("Faça o upload do(s) edital(is) para iniciar uma nova conversa.")
    
    arquivos_paola = st.file_uploader(
        "Upload de Documentos de Licitação (Máx: 100 MB)", 
        type=["pdf", "txt", "png", "jpg", "jpeg", "xlsx", "xls", "csv"], 
        accept_multiple_files=True, 
        key=st.session_state.key_uploader_paola
    )
    
    gemini_files_paola = []
    
    if arquivos_paola:
        for arquivo in arquivos_paola:
            if arquivo.size > 100 * 1024 * 1024:
                st.error(f"⚠️ O arquivo {arquivo.name} excede o limite de 100 MB.")
                continue
                
            file_hash_p = hash(arquivo.getvalue())
            
            if file_hash_p not in st.session_state.uploaded_gemini_files:
                with st.spinner(f"🤖 Paola está indexando {arquivo.name}..."):
                    ext = arquivo.name.split('.')[-1].lower()
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                        tmp.write(arquivo.getvalue())
                        tmp_path = tmp.name
                        
                    mime_paola = arquivo.type if arquivo.type else "application/octet-stream"
                    gemini_file = client.files.upload(
                        file=tmp_path, 
                        config=types.UploadFileConfig(
                            display_name=arquivo.name,
                            mime_type=mime_paola
                        )
                    )
                    
                    while gemini_file.state.name == "PROCESSING":
                        time.sleep(1)
                        gemini_file = client.files.get(name=gemini_file.name)
                        
                    st.session_state.uploaded_gemini_files[file_hash_p] = gemini_file
                    os.remove(tmp_path)
            
            gemini_files_paola.append(st.session_state.uploaded_gemini_files[file_hash_p])
        
        if gemini_files_paola:
            titulo_atual = "Múltiplos Arquivos" if len(arquivos_paola) > 1 else arquivos_paola[0].name
            if not st.session_state.conversa_paola_ukey:
                st.session_state.conversa_paola_ukey = criar_nova_conversa(f"Edital: {titulo_atual}", tipo="PAOLA")
            else:
                atualizar_titulo_conversa(st.session_state.conversa_paola_ukey, f"Edital: {titulo_atual}")
            
            if len(st.session_state.messages_paola) == 0:
                nomes_arquivos = ", ".join([a.name for a in arquivos_paola])
                intro_msg = f"Olá! Sou a **Paola**, sua assistente de editais da Petronect. Analisei: `{nomes_arquivos}`. Como posso ajudar com este edital?"
                st.session_state.messages_paola.append({"role": "model", "content": intro_msg})
                salvar_mensagem_banco(st.session_state.conversa_paola_ukey, "model", intro_msg)

    for msg in st.session_state.messages_paola:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_prompt_paola = st.chat_input("Digite sua dúvida sobre o edital para a Paola...")

    if user_prompt_paola:
        if not st.session_state.conversa_paola_ukey:
            st.session_state.conversa_paola_ukey = criar_nova_conversa("Consulta de Edital", tipo="PAOLA")

        st.session_state.messages_paola.append({"role": "user", "content": user_prompt_paola})
        salvar_mensagem_banco(st.session_state.conversa_paola_ukey, "user", user_prompt_paola)
        
        with st.chat_message("user"):
            st.markdown(user_prompt_paola)

        contents_paola = []
        if gemini_files_paola:
            contents_paola.extend(gemini_files_paola)
        contents_paola.append(user_prompt_paola)

        formatted_history_paola = []
        for m in st.session_state.messages_paola[:-1]:
            role = "user" if m["role"] == "user" else "model"
            formatted_history_paola.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
        
        partes_conteudo = []
        for item in contents_paola:
            if isinstance(item, str):
                partes_conteudo.append(types.Part.from_text(text=item))
            else:
                partes_conteudo.append(types.Part.from_uri(file_uri=item.uri, mime_type=item.mime_type))
                
        current_content_paola = types.Content(role="user", parts=partes_conteudo)
        formatted_history_paola.append(current_content_paola)

        system_instruction_paola = "Você é a Paola, assistente virtual oficial da Petronect para editais e licitações."

        with st.chat_message("model"):
            with st.spinner("🤖 Paola está analisando os arquivos..."):
                try:
                    response_p = client.models.generate_content(
                        model=MODEL_ID, 
                        contents=formatted_history_paola, 
                        config=types.GenerateContentConfig(system_instruction=system_instruction_paola, temperature=0.3)
                    )
                    resp_texto_p = response_p.text
                    st.markdown(resp_texto_p)

                    st.session_state.messages_paola.append({"role": "model", "content": resp_texto_p})
                    salvar_mensagem_banco(st.session_state.conversa_paola_ukey, "model", resp_texto_p)
                except Exception as e:
                    st.error(f"Erro na API do Gemini: {e}")