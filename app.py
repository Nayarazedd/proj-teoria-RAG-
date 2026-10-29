import os
import sqlite3
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI, APIError
import base64

# Carrega variáveis locais se existirem (para execução local com .env)
load_dotenv(override=True)

# Compatibilidade entre st.secrets e os nomes de variáveis de ambiente solicitados
def get_env_variable(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)

AZURE_ENDPOINT = get_env_variable("ENDPOINT")
AZURE_API_KEY = get_env_variable("API_KEY")
AZURE_API_VERSION = get_env_variable("API_VERSION", "2025-04-01-preview")
DEPLOYMENT_NAME = get_env_variable("GPT5_MODEL")

# Inicialização do Cliente Azure OpenAI
client = None
if AZURE_ENDPOINT and AZURE_API_KEY:
    try:
        client = AzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            api_key=AZURE_API_KEY,
            api_version=AZURE_API_VERSION
        )
    except Exception:
        pass

@st.cache_data(ttl=3600)
def raspar_site_dados():
    url = "https://gratuitos.netlify.app/"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove elementos indesejados
        for script in soup(["script", "style"]):
            script.extract()
            
        texto_limpo = soup.get_text(separator="\n")
        linhas = [linha.strip() for linha in texto_limpo.splitlines() if linha.strip()]
        return "\n".join(linhas)[:3000]
    except Exception as e:
        return f"Erro ao acessar o site: {e}"

@st.cache_data
def carregar_dados_locais():
    conteudo_csv = "dados.csv não encontrado."
    conteudo_pdf = "escola.pdf não encontrado."
    t_csv = "tic.csv não encontrado."
    dados_db = "Banco de dados vazio ou não encontrado."
    
    # Leitura de arquivo CSV 1
    try:
        if os.path.exists("dados.csv"):
            df = pd.read_csv("dados.csv")
            conteudo_csv = df.head(50).to_string(index=False)
    except Exception as e:
        conteudo_csv = f"Erro ao ler CSV: {e}"

    # Leitura de arquivo CSV 2 (TIC / Titanic)
    try:
        caminho_tic = "tic.csv"
        if not os.path.exists(caminho_tic) and os.path.exists("titanic.csv"):
            caminho_tic = "titanic.csv"
        if os.path.exists(caminho_tic):
            df_tic = pd.read_csv(caminho_tic)
            t_csv = df_tic.head(50).to_string(index=False)
    except Exception as e:
        t_csv = f"Erro ao ler tic.csv: {e}"

    # Leitura de arquivo PDF (escola.pdf ou arquivo.pdf)
    try:
        caminho_pdf = "escola.pdf"
        if not os.path.exists(caminho_pdf) and os.path.exists("arquivo.pdf"):
            caminho_pdf = "arquivo.pdf"
        
        if os.path.exists(caminho_pdf):
            reader = PdfReader(caminho_pdf)
            texto_pdf_list = []
            for pagina in reader.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    texto_pdf_list.append(texto_pagina)
            conteudo_pdf = "\n".join(texto_pdf_list)[:3000]
    except Exception as e:
        conteudo_pdf = f"Erro ao ler PDF: {e}"

    # Leitura do Banco SQLite (banco.db)
    try:
        if os.path.exists("banco.db"):
            con = sqlite3.connect("banco.db")
            cursor = con.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS vendas(
                             venda REAL,
                             vendedor TEXT,
                             id TEXT)''')
            con.commit()
            cursor.execute('SELECT * FROM vendas')
            dados_db = str(cursor.fetchall())
            con.close()
    except Exception as e:
        dados_db = f"Erro ao ler banco.db: {e}"

    return conteudo_csv, t_csv, conteudo_pdf, dados_db

def validar_configuracao():
    faltando = []
    if not AZURE_ENDPOINT:
        faltando.append("ENDPOINT")
    if not AZURE_API_KEY:
        faltando.append("API_KEY")
    if not DEPLOYMENT_NAME:
        faltando.append("GPT5_MODEL")
    return faltando

def main():
    st.set_page_config(page_title="Assistente Unificado & Visão", page_icon="🤖", layout="centered")
    
    st.title("🤖 Assistente Virtual Unificado & Visão Computacional")
    st.write("Consulte bases de dados institucionais via Chat RAG ou utilize a Visão Computacional da Azure.")

    faltando = validar_configuracao()
    if faltando:
        st.error(f"Erro de configuração: As seguintes variáveis não foram definidas no ambiente: {', '.join(faltando)}")
        return

    # Abas para separar o Chat RAG da Visão Computacional
    aba_chat, aba_visao = st.tabs(["💬 Chatbot RAG (Múltiplas Fontes)", "👁️ Visão Computacional (Azure)"])

    with aba_chat:
        st.subheader("Converse com o Assistente Inteligente")
        
        # Inicializa o histórico de mensagens no estado da sessão
        if "messages" not in st.session_state:
            st.session_state.messages = []

        # Carrega as bases com cache e limite de segurança
        with st.spinner("Carregando bases de conhecimento..."):
            dados_csv, t_csv, dados_pdf, dados_db = carregar_dados_locais()
            dados_site = raspar_site_dados()

        # Prompt unificado do sistema
        prompt_sistema = f"""
Você é um assistente de atendimento inteligente. Responda à dúvida do usuário utilizando EXCLUSIVAMENTE os contextos abaixo:

----[DADOS DO SITE]----
{dados_site}

----[CONTEÚDO DO PDF]----
{dados_pdf}

----[DADOS DO CSV 1]----
{dados_csv}

----[DADOS DO CSV 2 (TIC)]----
{t_csv}

----[BANCO DE DADOS DE VENDAS]----
{dados_db}
"""

        # Exibe histórico de mensagens
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Input de Chat na parte inferior
        if pergunta := st.chat_input("Digite sua dúvida, endereço, vendedor ou dado desejado..."):
            if not client:
                st.error("Cliente Azure OpenAI não inicializado.")
                return

            st.session_state.messages.append({"role": "user", "content": pergunta})
            with st.chat_message("user"):
                st.markdown(pergunta)

            mensagens_api = [{"role": "system", "content": prompt_sistema}]
            for m in st.session_state.messages:
                mensagens_api.append({"role": m["role"], "content": m["content"]})

            max_tentativas = 3
            resposta_texto = ""

            for tentativa in range(max_tentativas):
                try:
                    with st.spinner(f"Pensando... (Tentativa {tentativa+1})"):
                        response = client.chat.completions.create(
                            model=DEPLOYMENT_NAME,
                            messages=mensagens_api
                        )
                        resposta_texto = response.choices[0].message.content
                        break
                except APIError as e:
                    if getattr(e, 'status_code', None) == 429 or "429" in str(e):
                        if tentativa < max_tentativas - 1:
                            time.sleep(5)
                        else:
                            resposta_texto = "O limite de tokens da API foi atingido. Tente novamente em instantes."
                    else:
                        resposta_texto = f"Erro na API Azure: {e}"
                        break
                except Exception as e:
                    resposta_texto = f"Erro inesperado: {e}"
                    break

            st.session_state.messages.append({"role": "assistant", "content": resposta_texto})
            with st.chat_message("assistant"):
                st.markdown(resposta_texto)

    with aba_visao:
        st.subheader("Análise e Identificação de Objetos e Pessoas")
        st.write("Carregue uma imagem para que o agente da Azure analise e liste os objetos e pessoas presentes nela.")

        uploaded_file = st.file_uploader("Escolha uma imagem (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])

        if uploaded_file is not None:
            # Exibe a imagem usando o parâmetro width atualizado
            st.image(uploaded_file, caption="Imagem carregada", width='stretch')

            if st.button("Identificar Objetos e Pessoas"):
                if not client:
                    st.error("Cliente Azure OpenAI não inicializado corretamente.")
                    return

                try:
                    with st.spinner("Analisando imagem com Visão Computacional..."):
                        bytes_dados = uploaded_file.getvalue()
                        base64_imagem = base64.b64encode(bytes_dados).decode("utf-8")
                        mime_type = uploaded_file.type

                        response = client.chat.completions.create(
                            model=DEPLOYMENT_NAME,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text", 
                                            "text": "Você é um especialista em visão computacional. Identifique, descreva detalhadamente e liste todos os objetos, elementos e pessoas visíveis nesta imagem."
                                        },
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:{mime_type};base64,{base64_imagem}"
                                            }
                                        }
                                    ]
                                }
                            ],
                            max_completion_tokens=800
                        )
                        
                        resultado_visao = response.choices[0].message.content
                        st.markdown("### Resultado da Identificação:")
                        st.success(resultado_visao)

                except APIError as e:
                    st.error(f"Erro na API do Azure (Visão): {e}")
                except Exception as e:
                    st.error(f"Erro inesperado na visão computacional: {e}")

if __name__ == "__main__":
    main()