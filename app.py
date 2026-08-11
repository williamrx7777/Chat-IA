import streamlit as st
import os
import tempfile
import base64
import io
import sys
import wave
import re
import pandas as pd
from google import genai
from google.genai import types

# -------------------------------------------------------------------
# Configuração Inicial da Página
# -------------------------------------------------------------------
st.set_page_config(page_title="Gemini IA Chat & Analytcs", page_icon="🧠", layout="wide")
st.title("🧠 Gemini IA Chat Multimodal & Análise de Dados")

# Inicializa o cliente da nova SDK
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    st.error("⚠️ Defina a variável de ambiente GOOGLE_API_KEY com sua chave do AI Studio.")
    st.stop()

client = genai.Client(api_key=api_key)

# -------------------------------------------------------------------
# Funções Auxiliares - Áudio e Chat
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
    except Exception as e:
        print(f"Erro no serviço de TTS: {e}")
        return None

# -------------------------------------------------------------------
# Funções Auxiliares - Análise de Dados (Seu Script)
# -------------------------------------------------------------------
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
    print("=" * 70)
    print("CARREGANDO ARQUIVO")
    print("=" * 70)
    
    nome_arquivo = arquivo_st.name.lower()
    df = None
    
    # Verifica se o arquivo é Excel
    if nome_arquivo.endswith('.xlsx') or nome_arquivo.endswith('.xls'):
        try:
            # Lê o arquivo Excel
            df = pd.read_excel(arquivo_st)
            print("Arquivo Excel carregado com sucesso.")
        except Exception as e:
            raise Exception(f"Erro ao ler o arquivo Excel: {e}")
            
    # Se não for Excel, tenta ler como CSV usando a sua lógica original
    else:
        encodings = ["utf-8-sig", "latin1", "cp1252"]
        for encoding in encodings:
            try:
                arquivo_st.seek(0)
                df = pd.read_csv(arquivo_st, sep=None, engine="python", encoding=encoding)
                print(f"Encoding utilizado: {encoding}")
                break
            except UnicodeDecodeError:
                continue
                
    if df is None:
        raise Exception("Não foi possível processar o arquivo. Verifique o formato e a codificação.")
        
    print(f"Registros: {len(df):,}")
    print(f"Colunas: {len(df.columns)}")
    return df

def identificar_colunas(df):
    colunas = {}
    colunas["empresa"] = encontrar_coluna(df, ["EMPRESA", "FILIAL", "EMPRESA/FILIAL"])
    colunas["data"] = encontrar_coluna(df, ["DATA", "DATA EMISSAO", "DATA EMISSÃO", "DT EMISSAO", "DT EMISSÃO"])
    colunas["tipo"] = encontrar_coluna(df, ["TIPO", "TIPO NOTA", "TIPO NF", "TIPO MOVIMENTO"])
    colunas["status"] = encontrar_coluna(df, ["STATUS", "SITUACAO", "SITUAÇÃO"])
    colunas["produto"] = encontrar_coluna(df, ["PRODUTO", "DESCRICAO", "DESCRIÇÃO", "MATERIAL", "DESCRIÇÃO MATERIAL"])
    colunas["grupo"] = encontrar_coluna(df, ["GRUPO", "GRUPO PRODUTO", "GRUPO DE PRODUTO"])
    colunas["fabricante"] = encontrar_coluna(df, ["FABRICANTE", "MARCA"])
    colunas["vendedor"] = encontrar_coluna(df, ["VENDEDOR", "VENDEDOR(A)", "REPRESENTANTE"])
    colunas["cliente"] = encontrar_coluna(df, ["CLIENTE", "RAZAO SOCIAL", "RAZÃO SOCIAL"])
    colunas["valor"] = encontrar_coluna(df, ["VALOR", "VALOR NF", "VALOR NOTA", "TOTAL", "TOTAL NF", "VALOR TOTAL"])
    colunas["devolucao"] = encontrar_coluna(df, ["DEVOLUCAO", "DEVOLUÇÃO"])
    colunas["cancelamento"] = encontrar_coluna(df, ["CANCELAMENTO", "CANCELADO"])
    colunas["custo"] = encontrar_coluna(df, ["CUSTO", "CUSTO TOTAL"])
    colunas["margem"] = encontrar_coluna(df, ["MARGEM", "MARGEM TOTAL"])
    colunas["quantidade"] = encontrar_coluna(df, ["QUANTIDADE", "QTD", "QTDE"])
    return colunas

def preparar_dados(df, colunas):
    if colunas["data"]:
        df[colunas["data"]] = pd.to_datetime(df[colunas["data"]], errors="coerce", dayfirst=True)
    campos_numericos = ["valor", "devolucao", "cancelamento", "custo", "margem", "quantidade"]
    for campo in campos_numericos:
        coluna = colunas.get(campo)
        if coluna:
            df[coluna] = converter_numero(df[coluna])
    return df

def imprimir_relatorios(df, colunas):
    # Resumo Geral
    print("\n" + "=" * 70 + "\nRESUMO GERAL\n" + "=" * 70)
    print(f"\nTotal de registros: {len(df):,}")
    if colunas["data"]:
        data = df[colunas["data"]].dropna()
        if not data.empty:
            print(f"Período: {data.min().strftime('%d/%m/%Y')} a {data.max().strftime('%d/%m/%Y')}")
    if colunas["empresa"]:
        print("\nEMPRESAS:")
        for empresa, qtd in df[colunas["empresa"]].value_counts().items():
            print(f"  {empresa}: {qtd:,}")
    print("\nVALORES:")
    campos = [("valor", "Total NF"), ("devolucao", "Devoluções"), ("cancelamento", "Cancelamentos"),
              ("custo", "Custo"), ("margem", "Margem"), ("quantidade", "Quantidade")]
    valores = {}
    for campo, descricao in campos:
        coluna = colunas.get(campo)
        if coluna:
            total = df[coluna].sum()
            valores[campo] = total
            if campo == "quantidade":
                print(f"  {descricao}: {total:,.0f}")
            else:
                print(f"  {descricao}: {dinheiro(total)}")
    if "valor" in valores:
        liquido = valores["valor"]
        if "devolucao" in valores: liquido -= valores["devolucao"]
        if "cancelamento" in valores: liquido -= valores["cancelamento"]
        print(f"  Total líquido: {dinheiro(liquido)}")

    # Tipos e Status
    for key, titulo in [("tipo", "VENDAS X COMPRAS"), ("status", "STATUS")]:
        coluna = colunas.get(key)
        if coluna:
            print("\n" + "=" * 70 + f"\n{titulo}\n" + "=" * 70)
            for item, qtd in df[coluna].fillna("NÃO INFORMADO").value_counts().items():
                print(f"{item}: {qtd:,}")

    # Top Rankings
    rankings = [("grupo", "GRUPOS DE PRODUTOS"), ("produto", "PRODUTOS POR VALOR"), 
                ("fabricante", "FABRICANTES"), ("vendedor", "VENDEDORES"), ("cliente", "CLIENTES")]
    for key, titulo in rankings:
        col = colunas.get(key)
        val_col = colunas.get("valor")
        if col:
            print("\n" + "=" * 70 + f"\nTOP 10 {titulo}\n" + "=" * 70)
            if key == "grupo":
                res = df[col].fillna("NÃO INFORMADO").value_counts().head(10)
                for i, (nome, qtd) in enumerate(res.items(), 1): print(f"{i:02d}. {nome}: {qtd:,}")
            elif val_col:
                res = df.groupby(col)[val_col].sum().sort_values(ascending=False).head(10)
                for i, (nome, total) in enumerate(res.items(), 1): print(f"{i:02d}. {nome} — {dinheiro(total)}")

    # Vendas Tempo
    data_col = colunas.get("data")
    val_col = colunas.get("valor")
    if data_col and val_col:
        temp = df.dropna(subset=[data_col]).copy()
        temp["ANO"] = temp[data_col].dt.year
        print("\n" + "=" * 70 + "\nVENDAS POR ANO\n" + "=" * 70)
        for ano, total in temp.groupby("ANO")[val_col].sum().sort_index().items():
            print(f"{int(ano)}: {dinheiro(total)}")
            
        temp["ANO_MES"] = temp[data_col].dt.to_period("M").astype(str)
        print("\n" + "=" * 70 + "\nVENDAS POR MÊS\n" + "=" * 70)
        for periodo, total in temp.groupby("ANO_MES")[val_col].sum().sort_index().items():
            print(f"{periodo}: {dinheiro(total)}")

def exportar_excel_buffer(df, colunas):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Dados", index=False)
        for key, sheet_name in [("empresa", "Empresas"), ("grupo", "Grupos")]:
            if colunas[key]:
                df[colunas[key]].value_counts().reset_index().to_excel(writer, sheet_name=sheet_name, index=False)
        for key, sheet_name in [("produto", "Produtos"), ("fabricante", "Fabricantes"), 
                                ("vendedor", "Vendedores"), ("cliente", "Clientes")]:
            if colunas[key] and colunas["valor"]:
                df.groupby(colunas[key])[colunas["valor"]].sum().sort_values(ascending=False).reset_index().to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


# -------------------------------------------------------------------
# Gerenciamento de Estado (Session State)
# -------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "uploaded_gemini_files" not in st.session_state:
    st.session_state.uploaded_gemini_files = {}

# -------------------------------------------------------------------
# Barra Lateral (Sidebar)
# -------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configurações IA")
    use_thinking = st.toggle("Habilitar Pensamento Profundo", value=False)
    use_search = st.toggle("Habilitar Busca na Web", value=False)
    enable_voice_response = st.toggle("Habilitar Resposta por Voz", value=True)
    
    st.divider()
    st.header("🎙️ Entrada por Voz")
    voice_input = st.audio_input("Grave sua pergunta")
    
    st.divider()
    st.header("📎 Arquivos p/ IA")
    uploaded_file = st.file_uploader("Upload para IA analisar", type=["pdf", "txt", "png", "jpg", "jpeg", "csv", "xlsx", "xls"])
    
    if st.button("Limpar Histórico", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

MODEL_ID = "gemini-2.0-flash-thinking-exp-01-21" if use_thinking else "gemini-2.5-flash"

# -------------------------------------------------------------------
# Interface Principal em Abas (Tabs)
# -------------------------------------------------------------------
tab_chat, tab_dados = st.tabs(["💬 Chat com IA", "📊 Análise de Dados (CSV)"])

# ===================================================================
# ABA 1: CHAT IA (Seu código original mantido)
# ===================================================================
with tab_chat:
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "audio" in msg and msg["audio"]:
                st.audio(msg["audio"], format="audio/wav")

    text_prompt = st.chat_input("Digite sua mensagem para a IA...")
    prompt = None
    audio_prompt_file = None

    if text_prompt:
        prompt = text_prompt
    elif voice_input is not None:
        prompt = "🎙️ [Mensagem enviada por áudio]"
        audio_prompt_file = voice_input

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
            if audio_prompt_file:
                st.audio(audio_prompt_file)

        contents_to_send = []

        if uploaded_file is not None:
            file_hash = hash(uploaded_file.getvalue())
            if file_hash not in st.session_state.uploaded_gemini_files:
                with st.spinner("Preparando e enviando arquivo para a IA..."):
                    ext = uploaded_file.name.split('.')[-1].lower()
                    
                    # Se for Excel, convertemos para CSV temporário nos bastidores para a IA ler perfeitamente
                    if ext in ['xlsx', 'xls']:
                        df_excel = pd.read_excel(uploaded_file)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                            df_excel.to_csv(tmp.name, index=False, encoding="utf-8")
                            tmp_path = tmp.name
                    else:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                            tmp.write(uploaded_file.getvalue())
                            tmp_path = tmp.name
                            
                    gemini_file = client.files.upload(file=tmp_path, config=types.UploadFileConfig(display_name=uploaded_file.name))
                    st.session_state.uploaded_gemini_files[file_hash] = gemini_file
                    os.remove(tmp_path)
            contents_to_send.append(st.session_state.uploaded_gemini_files[file_hash])

        if audio_prompt_file is not None:
            with st.spinner("Processando áudio de entrada..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                    tmp.write(audio_prompt_file.getvalue())
                    tmp_audio_path = tmp.name
                audio_gemini_file = client.files.upload(file=tmp_audio_path)
                contents_to_send.append(audio_gemini_file)
                os.remove(tmp_audio_path)
        else:
            contents_to_send.append(prompt)

        tools = [types.Tool(google_search=types.GoogleSearch())] if use_search else None
        config = types.GenerateContentConfig(tools=tools, temperature=0.7 if not use_thinking else None)

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
            with st.spinner("Processando resposta..."):
                try:
                    response = client.models.generate_content(model=MODEL_ID, contents=formatted_history, config=config)
                    resposta_texto = response.text
                    audio_bytes = None
                    
                    st.markdown(resposta_texto)

                    if enable_voice_response:
                        with st.spinner("Gerando resposta em voz..."):
                            audio_bytes = gerar_audio_resposta(resposta_texto)
                            if audio_bytes:
                                st.audio(audio_bytes, format="audio/wav")
                            else:
                                st.warning("⚠️ Serviço de voz indisponível.")

                    st.session_state.messages.append({"role": "model", "content": resposta_texto, "audio": audio_bytes})
                except Exception as e:
                    st.error(f"Erro na API do Gemini: {e}")

# ===================================================================
# ABA 2: ANÁLISE DE DADOS (Novo Script Implementado)
# ===================================================================
with tab_dados:
    st.markdown("### 📊 Motor de Análise Rápida de Planilhas (CSV)")
    st.info("Faça o upload do seu arquivo CSV de vendas, notas fiscais ou faturamento. O sistema formatará e criará resumos gerenciais instantaneamente.")
    
    arquivo_dados = st.file_uploader("Selecione a base de dados (.csv, .xlsx, .xls)", type=["csv", "xlsx", "xls"], key="dados_analise")
    
    if arquivo_dados:
        try:
            with st.spinner("Lendo e estruturando dados... Isso pode levar um tempo para arquivos grandes."):
                # Executa o pipeline de dados
                df = carregar_dados(arquivo_dados)
                colunas = identificar_colunas(df)
                df = preparar_dados(df, colunas)
                
                # Exibe uma amostra dos dados na tela
                st.write("**Pré-visualização da Base Estruturada:**")
                st.dataframe(df.head(10), use_container_width=True)
                
                # Captura os prints do seu script original para exibir formatado no painel
                st.write("**Relatório Gerencial:**")
                
                # Redireciona a saída do terminal (prints) para capturar como texto
                old_stdout = sys.stdout
                sys.stdout = capture_stdout = io.StringIO()
                try:
                    imprimir_relatorios(df, colunas)
                finally:
                    sys.stdout = old_stdout
                
                # Exibe o relatório de texto capturado
                st.code(capture_stdout.getvalue(), language="text")
                
                # Gera o arquivo Excel para Download
                st.success("Análise concluída com sucesso! Baixe o relatório completo em Excel abaixo:")
                excel_data = exportar_excel_buffer(df, colunas)
                st.download_button(
                    label="📥 Baixar Relatório em Excel",
                    data=excel_data,
                    file_name="relatorio_analise.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
                
        except Exception as erro:
            st.error(f"Ocorreu um erro ao analisar os dados: {erro}")