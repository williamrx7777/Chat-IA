import streamlit as st
import os
import tempfile
import base64
import io
import sys
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
    st.error("⚠️ Credenciais do Supabase ausentes no .env")

# -------------------------------------------------------------------
# Funções de Banco de Dados (Supabase)
# -------------------------------------------------------------------
def validar_acesso_usuario(nome_input):
    if supabase:
        try:
            response = supabase.table("usuarios_permissoes").select("*").ilike("nome", nome_input).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
        except Exception as e:
            st.error(f"Erro ao validar acesso: {e}")
    return None

def criar_nova_conversa(titulo="Nova conversa", tipo="GERAL", usuario_ukey=None):
    novo_ukey = str(uuid.uuid4())
    if supabase:
        try:
            supabase.table("conversas_v2").insert({
                "ukey": novo_ukey, 
                "titulo": titulo, 
                "tipo": tipo,
                "usuario_ukey": usuario_ukey
            }).execute()
        except Exception as e:
            st.toast(f"Erro ao criar conversa no Supabase: {e}", icon="❌")
    return novo_ukey

def listar_conversas(usuario_ukey, tipo=None):
    conversas = []
    if supabase:
        try:
            query = supabase.table("conversas_v2").select("ukey, titulo, tipo").eq("usuario_ukey", usuario_ukey)
            if tipo:
                query = query.eq("tipo", tipo)
            response = query.order("data_criacao", desc=True).execute()
            
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
# Gerenciamento de Estado Inicial & Autenticação
# -------------------------------------------------------------------
if "usuario_logado" not in st.session_state:
    st.session_state.usuario_logado = None

if not st.session_state.usuario_logado:
    st.title("🔒 Acesso Restrito")
    nome_input = st.text_input("Digite seu Nome de Acesso:")
    
    if st.button("Entrar", use_container_width=True):
        if not nome_input.strip():
            st.warning("Por favor, insira um nome válido.")
        else:
            dados_usuario = validar_acesso_usuario(nome_input.strip())
            if dados_usuario:
                st.session_state.usuario_logado = dados_usuario
                st.success(f"Bem-vindo(a), {dados_usuario['nome']}!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Nome não encontrado na base de dados.")
    st.stop()

# -------------------------------------------------------------------
# Gerenciamento de Estado Pós-Login
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
# Funções Auxiliares - Áudio e Dados
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

def encontrar_coluna(df, nomes):
    mapa = {str(col).strip().upper(): col for col in df.columns}
    for nome in nomes:
        nome_normalizado = nome.strip().upper()
        if nome_normalizado in mapa:
            return mapa[nome_normalizado]
    return None

def converter_numero(serie):
    if pd.api.types.is_numeric_dtype(serie):
        return serie
    serie = (serie.astype(str).str.strip().str.replace("R$", "", regex=False)
             .str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(serie, errors="coerce").fillna(0)

def dinheiro(valor):
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

@st.cache_data
def carregar_dados(arquivo_st):
    nome_arquivo = arquivo_st.name.lower()
    df = None
    if nome_arquivo.endswith('.xlsx') or nome_arquivo.endswith('.xls'):
        df = pd.read_excel(arquivo_st)
    else:
        for encoding in ["utf-8-sig", "latin1", "cp1252"]:
            try:
                arquivo_st.seek(0)
                df = pd.read_csv(arquivo_st, sep=None, engine="python", encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
    if df is None:
        raise Exception("Não foi possível processar o arquivo.")
    return df

def identificar_colunas(df):
    colunas = {}
    colunas["empresa"] = encontrar_coluna(df, ["EMPRESA", "FILIAL", "EMPRESA/FILIAL", "LOJA"])
    colunas["tipo"] = encontrar_coluna(df, ["TIPO", "TIPO NOTA", "TIPO NF", "TIPO MOVIMENTO", "CFOP", "NATUREZA OPERACAO"])
    colunas["grupo"] = encontrar_coluna(df, ["GRUPO", "GRUPO PRODUTO", "GRUPO DE PRODUTO", "CATEGORIA", "LINHA"])
    colunas["margem"] = encontrar_coluna(df, ["MARGEM", "MARGEM TOTAL", "LUCRO"])
    colunas["quantidade"] = encontrar_coluna(df, ["QUANTIDADE", "QTD", "QTDE", "VOLUME"])
    colunas["vendedor"] = encontrar_coluna(df, ["VENDEDOR", "VENDEDOR(A)", "REPRESENTANTE", "VEND", "NOME VENDEDOR", "VENDEDORES", "VEND."])
    colunas["valor"] = encontrar_coluna(df, ["TOTAL_LIQU", "TOTAL_NF", "VALOR", "VALOR NF", "VALOR NOTA", "TOTAL", "TOTAL NF", "VALOR TOTAL", "VLR TOTAL", "TOTAL LIQUIDO", "FATURAMENTO"])
    colunas["periodo"] = encontrar_coluna(df, ["PERIODO", "PERÍODO", "OPERACAO", "OPERAÇÃO", "TIPO MOVIMENTO"])
    colunas["ano"] = encontrar_coluna(df, ["ANO", "YEAR", "EXERCICIO", "ANOS"])
    colunas["mes"] = encontrar_coluna(df, ["MES_N", "MES", "MÊS", "MONTH"])
    colunas["dia"] = encontrar_coluna(df, ["DIA", "DAY"])
    colunas["data"] = encontrar_coluna(df, ["DATA", "DATE", "DATA_EMISSAO", "DATA EMISSAO", "DT_EMISSAO", "EMISSAO"])
    return colunas

def preparar_dados(df, colunas):
    for campo in ["margem", "quantidade", "valor"]:
        coluna = colunas.get(campo)
        if coluna and coluna in df.columns:
            df[coluna] = converter_numero(df[coluna])
            
    col_ano = colunas.get("ano")
    col_mes = colunas.get("mes")
    col_data = colunas.get("data")
    
    if col_data and col_data in df.columns:
        try:
            dt_series = pd.to_datetime(df[col_data], errors='coerce')
            if not col_ano or col_ano not in df.columns or (df[col_ano] == 0).all():
                df['ANO_EXTRAIDO'] = dt_series.dt.year.fillna(0).astype(int)
                colunas["ano"] = 'ANO_EXTRAIDO'
            if not col_mes or col_mes not in df.columns or (df[col_mes] == 0).all():
                df['MES_EXTRAIDO'] = dt_series.dt.month.fillna(0).astype(int)
                colunas["mes"] = 'MES_EXTRAIDO'
        except Exception:
            pass

    final_col_mes = colunas.get("mes")
    if not final_col_mes or final_col_mes not in df.columns:
        df['MES_PADRAO'] = 1
        colunas["mes"] = 'MES_PADRAO'
    else:
        if not pd.api.types.is_numeric_dtype(df[final_col_mes]):
            meses_map = {
                'JAN': 1, 'FEV': 2, 'MAR': 3, 'ABR': 4, 'MAI': 5, 'JUN': 6, 
                'JUL': 7, 'AGO': 8, 'SET': 9, 'OUT': 10, 'NOV': 11, 'DEZ': 12,
                'JANEIRO': 1, 'FEVEREIRO': 2, 'MARCO': 3, 'MARÇO': 3, 'ABRIL': 4, 'MAIO': 5, 
                'JUNHO': 6, 'JULHO': 7, 'AGOSTO': 8, 'SETEMBRO': 9, 'OUTUBRO': 10, 
                'NOVEMBRO': 11, 'DEZEMBRO': 12
            }
            df[final_col_mes] = df[final_col_mes].astype(str).str.upper().str.strip().map(meses_map).fillna(1).astype(int)
        else:
            df[final_col_mes] = pd.to_numeric(df[final_col_mes], errors='coerce').fillna(0).astype(int)

    if col_ano and col_ano in df.columns:
        df[col_ano] = pd.to_numeric(df[col_ano], errors='coerce').fillna(0).astype(int)

    return df

def imprimir_relatorios(df, colunas):
    col_periodo = colunas.get("periodo")
    col_vend = colunas.get("vendedor")
    col_valor = colunas.get("valor")
    col_ano = colunas.get("ano")

    def gerar_bloco_resumo(df_sub, titulo_bloco, nome_cargo):
        print("=" * 70)
        print(f"RESUMO DE {titulo_bloco.upper()} (ISOLADO POR ANO)")
        print("=" * 70)
        print(f"\nTotal de registros na base: {len(df_sub):,}\n")

        if col_ano and col_ano in df_sub.columns:
            anos_disponiveis = sorted([a for a in df_sub[col_ano].unique() if a > 0])
            for ano_val in anos_disponiveis:
                df_ano = df_sub[df_sub[col_ano] == ano_val]
                print(f"--- 📅 ANO: {ano_val} ---")
                if col_valor and col_valor in df_ano.columns:
                    print(f"Total Financeiro: {dinheiro(df_ano[col_valor].sum())}")
                if col_vend and col_vend in df_ano.columns:
                    print(f"\nTOP 5 {nome_cargo.upper()}S:")
                    if col_valor and col_valor in df_ano.columns:
                        top = df_ano.groupby(col_vend)[col_valor].sum().sort_values(ascending=False).head(5)
                        for i, (nome, total) in enumerate(top.items(), 1):
                            print(f"    {i:02d}. {nome} — {dinheiro(total)}")
                print("\n")
        else:
            if col_valor and col_valor in df_sub.columns:
                print(f"Total Financeiro: {dinheiro(df_sub[col_valor].sum())}")
            print("\n")

    if col_periodo and col_periodo in df.columns:
        serie_periodo = df[col_periodo].astype(str).str.upper().str.strip()
        df_vendas = df[serie_periodo.isin(["VENDAS", "VENDA", "V"])]
        if len(df_vendas) > 0:
            gerar_bloco_resumo(df_vendas, "VENDAS", "Vendedor")
    else:
        gerar_bloco_resumo(df, "GERAL", "Responsável")

# -------------------------------------------------------------------
# Barra Lateral (Sidebar)
# -------------------------------------------------------------------
usuario_atual_ukey = st.session_state.usuario_logado["ukey_usuario"]

with st.sidebar:
    st.markdown(f"👤 Logado como: **{st.session_state.usuario_logado['nome']}**")
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

    lista_chats = listar_conversas(usuario_ukey=usuario_atual_ukey)
    if lista_chats:
        icones_tipo = {"GERAL": "💬", "DADOS": "📊", "PAOLA": "📑"}
        for item in lista_chats:
            ukey = item[0]
            titulo = item[1]
            tipo_chat = item[2] if len(item) > 2 else "GERAL"
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

MODEL_ID = "gemini-3.5-flash" if use_thinking else "gemini-2.5-flash"

# -------------------------------------------------------------------
# Interface Principal em Abas (Tabs)
# -------------------------------------------------------------------
permissoes = st.session_state.usuario_logado

titulos_abas = []
if permissoes.get("acesso_chat"):
    titulos_abas.append("💬 Chat Geral com IA")
if permissoes.get("acesso_dados"):
    titulos_abas.append("📊 Análise de Dados & Chat")
if permissoes.get("acesso_paola"):
    titulos_abas.append("💬 Paola - Petronect (Editais)")

if not titulos_abas:
    st.warning("Seu usuário não possui acesso a nenhum módulo. Contate o administrador.")
    st.stop()

abas_renderizadas = st.tabs(titulos_abas)
indice_aba = 0

# ===================================================================
# ABA 1: CHAT GERAL COM IA
# ===================================================================
if permissoes.get("acesso_chat"):
    with abas_renderizadas[indice_aba]:
        st.markdown("### 💬 Chat Geral com IA")
        if not st.session_state.conversa_ativa_ukey and not st.session_state.messages:
            st.info("💡 Inicie uma nova conversa digitando abaixo ou selecione um histórico na barra lateral.")

        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        text_prompt = st.chat_input("Pergunte algo à IA...")
        prompt = None
        audio_prompt_file = None

        if text_prompt:
            prompt = text_prompt
        elif voice_input is not None:
            prompt = "🎙️ [Mensagem enviada por áudio]"
            audio_prompt_file = voice_input

        if prompt:
            if not st.session_state.conversa_ativa_ukey:
                st.session_state.conversa_ativa_ukey = criar_nova_conversa(prompt[:45], tipo="GERAL", usuario_ukey=usuario_atual_ukey)
            elif len(st.session_state.messages) == 0:
                atualizar_titulo_conversa(st.session_state.conversa_ativa_ukey, prompt)

            st.session_state.messages.append({"role": "user", "content": prompt})
            salvar_mensagem_banco(st.session_state.conversa_ativa_ukey, "user", prompt)
            
            with st.chat_message("user"):
                st.markdown(prompt)
                if audio_prompt_file:
                    st.audio(audio_prompt_file)

            contents_to_send = []
            if audio_prompt_file is not None:
                with st.spinner("Processando áudio de entrada..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                        tmp.write(audio_prompt_file.getvalue())
                        tmp_audio_path = tmp.name
                    audio_gemini_file = client.files.upload(file=tmp_audio_path)
                    
                    while audio_gemini_file.state.name == "PROCESSING":
                        time.sleep(1)
                        audio_gemini_file = client.files.get(name=audio_gemini_file.name)
                        
                    contents_to_send.append(audio_gemini_file)
                    os.remove(tmp_audio_path)
            else:
                contents_to_send.append(prompt)

            tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
            config = types.GenerateContentConfig(tools=tools, temperature=0.7)

            formatted_history = []
            for m in st.session_state.messages[:-1]:
                role = "user" if m["role"] == "user" else "model"
                formatted_history.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
            
            current_content = types.Content(
                role="user", 
                parts=[types.Part.from_text(text=item) if isinstance(item, str) else types.Part.from_uri(file_uri=item.uri, mime_type=item.mime_type) for item in contents_to_send]
            )
            formatted_history.append(current_content)

            with st.chat_message("model"):
                with st.spinner("Pensando..."):
                    try:
                        response = client.models.generate_content(model=MODEL_ID, contents=formatted_history, config=config)
                        resposta_texto = response.text
                        
                        st.markdown(resposta_texto)

                        if enable_voice_response:
                            with st.spinner("Gerando resposta em voz..."):
                                audio_bytes = gerar_audio_resposta(resposta_texto)
                                if audio_bytes:
                                    st.audio(audio_bytes, format="audio/wav")

                        st.session_state.messages.append({"role": "model", "content": resposta_texto})
                        salvar_mensagem_banco(st.session_state.conversa_ativa_ukey, "model", resposta_texto)
                    except Exception as e:
                        st.error(f"Erro na API do Gemini: {e}")
    indice_aba += 1

# ===================================================================
# ABA 2: ANÁLISE DE DADOS & CHAT INTERATIVO (Com Filtros de Vendas/Compras)
# ===================================================================
if permissoes.get("acesso_dados"):
    with abas_renderizadas[indice_aba]:
        st.markdown("### 📊 Análise de Dados & Chat Interativo")
        
        if not st.session_state.conversa_dados_ukey and not st.session_state.messages_dados:
            st.info("💡 Faça o upload de uma planilha (.csv, .xlsx, .xls) para iniciar uma nova análise interativa ou selecione um histórico na barra lateral.")
        else:
            st.info("💡 Continue a consulta atual ou selecione um histórico na barra lateral.")

        arquivo_dados = st.file_uploader(
            "Selecione a base de dados (.csv, .xlsx, .xls)", 
            type=["csv", "xlsx", "xls"], 
            key=st.session_state.key_uploader_dados
        )
        
        gemini_file_dados = None
        relatorio_texto = ""

        if arquivo_dados:
            try:
                file_hash_d = hash(arquivo_dados.getvalue())
                if file_hash_d not in st.session_state.uploaded_gemini_files:
                    with st.spinner(f"🤖 Processando e indexando {arquivo_dados.name} no Gemini..."):
                        ext = arquivo_dados.name.split('.')[-1].lower()
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                            tmp.write(arquivo_dados.getvalue())
                            tmp_path = tmp.name
                            
                        gemini_f = client.files.upload(file=tmp_path, config=types.UploadFileConfig(display_name=arquivo_dados.name))
                        
                        while gemini_f.state.name == "PROCESSING":
                            time.sleep(1)
                            gemini_f = client.files.get(name=gemini_f.name)
                            
                        if gemini_f.state.name == "FAILED":
                            raise Exception("O processamento do arquivo falhou nos servidores do Google.")

                        st.session_state.uploaded_gemini_files[file_hash_d] = gemini_f
                        os.remove(tmp_path)
                
                gemini_file_dados = st.session_state.uploaded_gemini_files[file_hash_d]

                df = carregar_dados(arquivo_dados)
                colunas = identificar_colunas(df)
                df = preparar_dados(df, colunas)
                
                col_ano = colunas.get("ano")
                col_mes = colunas.get("mes")
                col_operacao = colunas.get("periodo") or colunas.get("tipo")
                
                f_col1, f_col2, f_col3 = st.columns(3)
                with f_col1:
                    if col_ano and col_ano in df.columns:
                        anos_unicos = sorted([int(a) for a in df[col_ano].unique() if a > 0])
                        if anos_unicos:
                            anos_selecionados = st.multiselect("📅 Filtrar Anos:", options=anos_unicos, default=anos_unicos, key="filtro_ano_tab2")
                            if anos_selecionados:
                                df = df[df[col_ano].isin(anos_selecionados)]
                with f_col2:
                    if col_mes and col_mes in df.columns:
                        meses_nomes = {1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"}
                        meses_selecionados = st.multiselect("📆 Filtrar Meses:", options=list(range(1, 13)), format_func=lambda x: meses_nomes.get(x, str(x)), default=list(range(1, 13)), key="filtro_mes_tab2")
                        if meses_selecionados:
                            df = df[df[col_mes].isin(meses_selecionados)]
                with f_col3:
                    if col_operacao and col_operacao in df.columns:
                        operacoes_unicas = sorted(df[col_operacao].astype(str).unique())
                        
                        if "filtro_operacao_val" not in st.session_state:
                            st.session_state.filtro_operacao_val = operacoes_unicas

                        operacoes_selecionadas = st.multiselect(
                            "🏷️ Filtrar Operação (Vendas/Compras):", 
                            options=operacoes_unicas, 
                            default=st.session_state.filtro_operacao_val, 
                            key="filtro_operacao_tab2"
                        )
                        st.session_state.filtro_operacao_val = operacoes_selecionadas
                        
                        if operacoes_selecionadas:
                            df = df[df[col_operacao].astype(str).isin(operacoes_selecionadas)]

                with st.expander("👁️ Visualizar Dados e Relatório Técnico", expanded=False):
                    st.write("**Pré-visualização da Base (Filtrada):**")
                    st.dataframe(df.head(10), use_container_width=True)
                    
                    old_stdout = sys.stdout
                    sys.stdout = capture_stdout = io.StringIO()
                    try:
                        imprimir_relatorios(df, colunas)
                    finally:
                        sys.stdout = old_stdout
                    
                    relatorio_texto = capture_stdout.getvalue()
                    st.code(relatorio_texto, language="text")

                titulo_analise = f"Análise: {arquivo_dados.name}"
                if not st.session_state.conversa_dados_ukey:
                    st.session_state.conversa_dados_ukey = criar_nova_conversa(titulo_analise, tipo="DADOS", usuario_ukey=usuario_atual_ukey)
                else:
                    atualizar_titulo_conversa(st.session_state.conversa_dados_ukey, titulo_analise)
                    
                if len(st.session_state.messages_dados) == 0:
                    intro_msg_d = f"Olá! Analisei a base de dados `{arquivo_dados.name}`. O que você gostaria de detalhar, cruzar de informações ou tirar dúvidas sobre estes dados?"
                    st.session_state.messages_dados.append({"role": "model", "content": intro_msg_d})
                    salvar_mensagem_banco(st.session_state.conversa_dados_ukey, "model", intro_msg_d)

            except Exception as erro:
                st.error(f"Erro ao analisar os dados: {erro}")

        # Botões de Acesso Rápido com atualização direta dos filtros de Vendas/Compras e reexecução da tela
        col_db1, col_db2, col_db3, col_db4, col_db5 = st.columns(5)
        quick_prompt_dados = None
        
        with col_db1:
            if st.button("📈 Faturamento", key="qb_fat"):
                quick_prompt_dados = "Qual é o faturamento total e principais métricas financeiras desta base de dados?"
        with col_db2:
            if st.button("🏆 Melhores", key="qb_top"):
                quick_prompt_dados = "Quem são os principais destaques (vendedores, filiais ou grupos) com base nos valores apresentados?"
        with col_db3:
            if st.button("💡 Insights", key="qb_ins"):
                quick_prompt_dados = "Quais insights estratégicos ou pontos de atenção você destaca nesta base de dados?"
        with col_db4:
            if st.button("🛒 Analisar Vendas", key="qb_vendas"):
                if 'col_operacao' in locals() and col_operacao and col_operacao in df.columns:
                    vendas_opts = [op for op in operacoes_unicas if any(t in op.upper() for t in ["VENDA", "VENDAS", "V"])]
                    if vendas_opts:
                        st.session_state.filtro_operacao_val = vendas_opts
                quick_prompt_dados = "Analise detalhadamente o desempenho e os totais exclusivos das operações de Vendas filtradas."
                st.rerun()
        with col_db5:
            if st.button("📦 Analisar Compras", key="qb_compras"):
                if 'col_operacao' in locals() and col_operacao and col_operacao in df.columns:
                    compras_opts = [op for op in operacoes_unicas if any(t in op.upper() for t in ["COMPRA", "COMPRAS", "C"])]
                    if compras_opts:
                        st.session_state.filtro_operacao_val = compras_opts
                quick_prompt_dados = "Analise detalhadamente os volumes, custos e totais exclusivos das operações de Compras filtradas."
                st.rerun()

        for msg in st.session_state.messages_dados:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_prompt_dados = st.chat_input("Digite sua dúvida sobre a planilha ou peça uma nova análise...")

        prompt_final_dados = None
        if quick_prompt_dados:
            prompt_final_dados = quick_prompt_dados
        elif user_prompt_dados:
            prompt_final_dados = user_prompt_dados

        if prompt_final_dados:
            if not st.session_state.conversa_dados_ukey:
                st.session_state.conversa_dados_ukey = criar_nova_conversa("Consulta de Dados", tipo="DADOS", usuario_ukey=usuario_atual_ukey)

            st.session_state.messages_dados.append({"role": "user", "content": prompt_final_dados})
            salvar_mensagem_banco(st.session_state.conversa_dados_ukey, "user", prompt_final_dados)
            
            with st.chat_message("user"):
                st.markdown(prompt_final_dados)

            is_primeira_interacao = len(st.session_state.messages_dados) == 1

            contents_dados = []
            if gemini_file_dados and is_primeira_interacao:
                contents_dados.append(gemini_file_dados)
            
            contexto_relatorio = f"\n[Relatório Técnico Computado com os filtros ativos atuais]: \n{relatorio_texto}\n" if relatorio_texto else ""
            contents_dados.append(prompt_final_dados + contexto_relatorio)

            formatted_history_dados = []
            for m in st.session_state.messages_dados[:-1]:
                role = "user" if m["role"] == "user" else "model"
                formatted_history_dados.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))
            
            partes_conteudo_d = []
            for item in contents_dados:
                if isinstance(item, str):
                    partes_conteudo_d.append(types.Part.from_text(text=item))
                else:
                    partes_conteudo_d.append(types.Part.from_uri(file_uri=item.uri, mime_type=item.mime_type))
                    
            current_content_d = types.Content(role="user", parts=partes_conteudo_d)
            formatted_history_dados.append(current_content_d)

            system_instruction_dados = "Você é um analista de dados especialista em negócios. Responda com base estrita na planilha, nos filtros ativos (Vendas/Compras) e nos relatórios técnicos enviados. Forneça respostas diretas, números precisos e explicações úteis."

            with st.chat_message("model"):
                with st.spinner("🤖 Analisando dados..."):
                    try:
                        response_d = client.models.generate_content(
                            model=MODEL_ID, 
                            contents=formatted_history_dados, 
                            config=types.GenerateContentConfig(system_instruction=system_instruction_dados, temperature=0.3)
                        )
                        resp_texto_d = response_d.text
                        st.markdown(resp_texto_d)

                        if enable_voice_response:
                            with st.spinner("Gerando resposta em voz..."):
                                audio_bytes_d = gerar_audio_resposta(resp_texto_d)
                                if audio_bytes_d:
                                    st.audio(audio_bytes_d, format="audio/wav")

                        st.session_state.messages_dados.append({"role": "model", "content": resp_texto_d})
                        salvar_mensagem_banco(st.session_state.conversa_dados_ukey, "model", resp_texto_d)
                    except Exception as e:
                        st.error(f"Erro na API do Gemini: {e}")
    indice_aba += 1

# ===================================================================
# ABA 3: PAOLA - PETRONECT (EDITAIS E LICITAÇÕES)
# ===================================================================
if permissoes.get("acesso_paola"):
    with abas_renderizadas[indice_aba]:
        st.markdown("### 💬 Paola - Assistente Virtual de Editais (Petronect)")
        
        if not st.session_state.conversa_paola_ukey and not st.session_state.messages_paola:
            st.info("Faça o upload do(s) edital(is) e planilha(s) para iniciar uma nova conversa ou selecione um histórico na barra lateral.")
        else:
            st.info("Continue a consulta atual ou selecione um histórico na barra lateral.")
        
        arquivos_paola = st.file_uploader(
            "Upload de Documentos e Planilhas de Licitação (Máx: 100 MB)", 
            type=["pdf", "txt", "png", "jpg", "jpeg", "xlsx", "xls", "csv"], 
            accept_multiple_files=True, 
            key=st.session_state.key_uploader_paola
        )
        
        gemini_files_paola = []
        
        if arquivos_paola:
            for arquivo in arquivos_paola:
                if arquivo.size > 100 * 1024 * 1024:
                    st.error(f"⚠️ O arquivo {arquivo.name} excede o limite de **100 MB**.")
                    continue
                    
                file_hash_p = hash(arquivo.getvalue())
                
                if file_hash_p not in st.session_state.uploaded_gemini_files:
                    with st.spinner(f"🤖 Paola está lendo e indexando {arquivo.name}..."):
                        ext = arquivo.name.split('.')[-1].lower()
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                            tmp.write(arquivo.getvalue())
                            tmp_path = tmp.name
                            
                        gemini_file = client.files.upload(file=tmp_path, config=types.UploadFileConfig(display_name=arquivo.name))
                        
                        while gemini_file.state.name == "PROCESSING":
                            time.sleep(1)
                            gemini_file = client.files.get(name=gemini_file.name)
                            
                        st.session_state.uploaded_gemini_files[file_hash_p] = gemini_file
                        os.remove(tmp_path)
                
                gemini_files_paola.append(st.session_state.uploaded_gemini_files[file_hash_p])
            
            if gemini_files_paola:
                titulo_atual = "Múltiplos Arquivos" if len(arquivos_paola) > 1 else arquivos_paola[0].name
                if not st.session_state.conversa_paola_ukey:
                    st.session_state.conversa_paola_ukey = criar_nova_conversa(f"Edital: {titulo_atual}", tipo="PAOLA", usuario_ukey=usuario_atual_ukey)
                else:
                    atualizar_titulo_conversa(st.session_state.conversa_paola_ukey, f"Edital: {titulo_atual}")
                
                if len(st.session_state.messages_paola) == 0:
                    nomes_arquivos = ", ".join([a.name for a in arquivos_paola])
                    intro_msg = f"Olá! Sou a **Paola**, sua assistente virtual de editais da Petronect. Analisei o(s) documento(s): `{nomes_arquivos}`. Como posso ajudar você a cruzar essas informações e tirar suas dúvidas para a proposta hoje?"
                    st.session_state.messages_paola.append({"role": "model", "content": intro_msg})
                    salvar_mensagem_banco(st.session_state.conversa_paola_ukey, "model", intro_msg)

        col_pb1, col_pb2, col_pb3 = st.columns(3)
        quick_prompt_paola = None
        with col_pb1:
            if st.button("📅 Qual o prazo de entrega/proposta?", key="qb_prazo"):
                quick_prompt_paola = "Quais são as datas limite, prazos de entrega ou prazos para envio de propostas descritos nos anexos?"
        with col_pb2:
            if st.button("📋 Quais documentos são exigidos?", key="qb_docs"):
                quick_prompt_paola = "Quais documentos de habilitação, certidões ou qualificações são exigidos dos fornecedores nestes arquivos?"
        with col_pb3:
            if st.button("💰 Tem planilha de custos/valores?", key="qb_criterio"):
                quick_prompt_paola = "Existem planilhas de custos ou referências de valor estimado nestes arquivos? Se sim, resuma os valores e itens."

        for msg in st.session_state.messages_paola:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_prompt_paola = st.chat_input("Digite sua dúvida sobre o edital ou planilhas para a Paola...")
        
        prompt_final_paola = None
        if quick_prompt_paola:
            prompt_final_paola = quick_prompt_paola
        elif user_prompt_paola:
            prompt_final_paola = user_prompt_paola

        if prompt_final_paola:
            if not st.session_state.conversa_paola_ukey:
                st.session_state.conversa_paola_ukey = criar_nova_conversa("Consulta de Edital", tipo="PAOLA", usuario_ukey=usuario_atual_ukey)

            st.session_state.messages_paola.append({"role": "user", "content": prompt_final_paola})
            salvar_mensagem_banco(st.session_state.conversa_paola_ukey, "user", prompt_final_paola)
            
            with st.chat_message("user"):
                st.markdown(prompt_final_paola)

            contents_paola = []
            if gemini_files_paola:
                contents_paola.extend(gemini_files_paola)
            contents_paola.append(prompt_final_paola)

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

            system_instruction_paola = "Você é a Paola, assistente virtual oficial da Petronect para editais e licitações. Responda com base estrita nos documentos e planilhas enviados. Se enviaram um PDF de regras e um Excel de custos, relacione as informações de ambos quando necessário para responder às dúvidas do fornecedor."

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

                        if enable_voice_response:
                            with st.spinner("Gerando resposta em voz..."):
                                audio_bytes_p = gerar_audio_resposta(resp_texto_p)
                                if audio_bytes_p:
                                    st.audio(audio_bytes_p, format="audio/wav")

                        st.session_state.messages_paola.append({"role": "model", "content": resp_texto_p})
                        salvar_mensagem_banco(st.session_state.conversa_paola_ukey, "model", resp_texto_p)
                    except Exception as e:
                        st.error(f"Erro na API do Gemini: {e}")
    indice_aba += 1