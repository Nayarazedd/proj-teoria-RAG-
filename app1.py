import os
import time
import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI, APIError
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker
import base64

# Carrega variáveis de ambiente
load_dotenv(override=True)

ENDPOINT = os.getenv("ENDPOINT")
API_KEY = os.getenv("API_KEY")
API_VERSION = os.getenv("API_VERSION", "2025-04-01-preview")
GPT5_MODEL = os.getenv("GPT5_MODEL")

# Inicialização segura do Cliente Azure OpenAI
client = None
try:
    if ENDPOINT and API_KEY:
        client = AzureOpenAI(
            azure_endpoint=ENDPOINT,
            api_key=API_KEY,
            api_version=API_VERSION
        )
except Exception as e:
    print(f"Erro ao inicializar cliente Azure: {e}")

# --- ARQUITETURA ORM (SQLALCHEMY) - FOCO EM ESTUDOS ---
Base = declarative_base()

class UsuarioModel(Base):
    __tablename__ = 'usuarios'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    senha = Column(String, nullable=False)

class MateriaModel(Base):
    __tablename__ = 'materias'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False)
    nome = Column(String, nullable=False)
    professor = Column(String)

class TarefaModel(Base):
    __tablename__ = 'tarefas_estudo'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False)
    titulo = Column(String, nullable=False)
    materia = Column(String)
    prazo = Column(String)
    status = Column(String, default="Pendente")

class HistoricoModel(Base):
    __tablename__ = 'historico_chat'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String)
    role = Column(String)
    content = Column(String)

# Configuração do engine SQLite seguro via ORM
engine = create_engine('sqlite:///banco_estudos.db', echo=False)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def cadastrar_usuario(username, senha):
    try:
        session = SessionLocal()
        existe = session.query(UsuarioModel).filter_by(username=username).first()
        if existe:
            session.close()
            return False, "Usuário já existe!"
        
        novo_usuario = UsuarioModel(username=username, senha=senha)
        session.add(novo_usuario)
        session.commit()
        session.close()
        return True, "Cadastro realizado com sucesso!"
    except Exception as e:
        return False, f"Erro ao cadastrar: {e}"

def autenticar_usuario(username, senha):
    try:
        session = SessionLocal()
        usuario = session.query(UsuarioModel).filter_by(username=username, senha=senha).first()
        session.close()
        return usuario is not None
    except Exception as e:
        print(f"Erro na autenticação: {e}")
        return False

def salvar_historico_orm(username, role, content):
    try:
        session = SessionLocal()
        nova_msg = HistoricoModel(username=username, role=role, content=content)
        session.add(nova_msg)
        session.commit()
        session.close()
    except Exception as e:
        print(f"Erro ao salvar histórico: {e}")

def carregar_historico_orm(username):
    try:
        session = SessionLocal()
        mensagens = session.query(HistoricoModel).filter_by(username=username).all()
        session.close()
        return [{"role": m.role, "content": m.content} for m in mensagens]
    except Exception as e:
        print(f"Erro ao carregar histórico: {e}")
        return []

# --- FUNÇÕES DE RETRIEVAL COM FALLBACKS ---

@st.cache_data(ttl=1800)
def raspar_site():
    url = "https://gratuitos.netlify.app/"
    try:
        response = requests.get(url, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style"]):
            script.extract()
        texto = soup.get_text(separator="\n", strip=True)
        return texto[:3000] if texto else "[Site vazio]"
    except Exception as e:
        return f"[Fallback: Site indisponível - {e}]"

@st.cache_data
def ler_pdf():
    caminho_pdf = "arquivo.pdf"
    if not os.path.exists(caminho_pdf):
        if os.path.exists("escola.pdf"):
            caminho_pdf = "escola.pdf"
        else:
            return "[Fallback: PDF não encontrado]"
    try:
        reader = PdfReader(caminho_pdf)
        texto = ""
        for page in reader.pages:
            texto += page.extract_text() or ""
        return texto[:3000] if texto.strip() else "[PDF sem texto legível]"
    except Exception as e:
        return f"[Fallback: Erro ao ler PDF - {e}]"

def carregar_dados_academicos(username):
    try:
        if os.path.exists('dados.csv'):
            dados_csv = pd.read_csv('dados.csv').head(50).to_string()
        else:
            dados_csv = "[dados.csv não encontrado]"
    except Exception as e:
        dados_csv = f"[Erro CSV: {e}]"

    try:
        session = SessionLocal()
        tarefas = session.query(TarefaModel).filter_by(username=username).all()
        materias = session.query(MateriaModel).filter_by(username=username).all()
        
        if not tarefas:
            session.add(TarefaModel(username=username, titulo="Entrega do Projeto de IA", materia="Inteligência Artificial", prazo="Próxima Sexta", status="Pendente"))
            session.add(TarefaModel(username=username, titulo="Lista de Exercícios ORM", materia="Banco de Dados", prazo="Segunda-feira", status="Pendente"))
            session.commit()
            tarefas = session.query(TarefaModel).filter_by(username=username).all()
            
        session.close()
        
        dados_estudo = f"Tarefas/Prazos: {str([(t.titulo, t.materia, t.prazo, t.status) for t in tarefas])}"
    except Exception as e:
        dados_estudo = f"[Erro ORM Acadêmico: {e}]"

    return dados_csv, dados_estudo

# --- ORQUESTRADOR INTELIGENTE ACADÊMICO ---
def orquestrar_estudos(pergunta, username):
    pergunta_lower = pergunta.lower()
    
    foca_tarefas = any(k in pergunta_lower for k in ["tarefa", "prova", "prazo", "trabalho", "agenda", "estudar"])
    foca_conteudo = any(k in pergunta_lower for k in ["curso", "aula", "materia", "conteudo", "resumo"])
    foca_documentos = any(k in pergunta_lower for k in ["pdf", "regulamento", "documento", "regra", "apostila"])

    logs = []
    contexto_final = ""

    if not (foca_tarefas or foca_conteudo or foca_documentos):
        logs.append("🌐 **Orquestração Geral**: Acionando **Fluxo Acadêmico Completo** (Material, PDF e Agenda)...")
        site = raspar_site()
        pdf = ler_pdf()
        csv_geral, agenda = carregar_dados_academicos(username)
        logs.append("✅ Dados institucionais, apostilas e tarefas carregados.")
        contexto_final = f"""
----[CONTEÚDO DO SITE/CURSO]----
{site}
----[APOSTILA / PDF]----
{pdf}
----[DADOS GERAIS]----
{csv_geral}
----[AGENDA E TAREFAS DO ALUNO]----
{agenda}
"""
    else:
        logs.append("🎯 **Orquestração Seletiva de Estudos**: Direcionando ferramentas...")
        contexto_final = "Contexto Acadêmico Direcionado:\n"
        
        if foca_conteudo or "site" in pergunta_lower:
            logs.append("🔍 Consultando Portal Educacional...")
            contexto_final += f"\n[CONTEÚDO DO SITE]:\n{raspar_site()}"
        if foca_documentos or "pdf" in pergunta_lower:
            logs.append("🔍 Consultando Apostila em PDF...")
            contexto_final += f"\n[APOSTILA / PDF]:\n{ler_pdf()}"
        if foca_tarefas:
            logs.append("🔍 Consultando Agenda e Prazos via ORM...")
            _, agenda = carregar_dados_academicos(username)
            contexto_final += f"\n[AGENDA DO ALUNO]:\n{agenda}"
        
        csv_geral, _ = carregar_dados_academicos(username)
        contexto_final += f"\n[DADOS COMPLEMENTARES]:\n{csv_geral}"
        logs.append("✅ Contexto de estudos estruturado com sucesso.")

    return contexto_final, logs

# --- TELA DE LOGIN E CADASTRO ---
def tela_autenticacao():
    st.set_page_config(page_title="Login - Tutor Acadêmico", page_icon="🔐", layout="centered")
    st.title("🔐 Portal do Estudante - Agente IA")
    st.write("Faça login para acessar seu assistente de estudos e cronograma acadêmico.")

    aba_login, aba_cadastro = st.tabs(["🔑 Entrar", "📝 Criar Conta"])

    with aba_login:
        with st.form("form_login"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            submit_login = st.form_submit_button("Entrar")

            if submit_login:
                if autenticar_usuario(usuario, senha):
                    st.session_state["autenticado"] = True
                    st.session_state["usuario"] = usuario
                    st.success("Login realizado com sucesso! Entrando...")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")

    with aba_cadastro:
        with st.form("form_cadastro"):
            novo_usuario = st.text_input("Escolha um Usuário")
            nova_senha = st.text_input("Escolha uma Senha", type="password")
            submit_cadastro = st.form_submit_button("Cadastrar")

            if submit_cadastro:
                if not novo_usuario.strip() or not nova_senha.strip():
                    st.warning("Preencha todos os campos!")
                else:
                    sucesso, msg = cadastrar_usuario(novo_usuario, nova_senha)
                    if sucesso:
                        st.success(msg)
                    else:
                        st.error(msg)

# --- APLICAÇÃO PRINCIPAL (TUTOR ACADÊMICO) ---
def main_app():
    st.set_page_config(page_title="Tutor Acadêmico IA", page_icon="🎓", layout="centered")

    with st.sidebar:
        st.write(f"🎓 Estudante: **{st.session_state['usuario']}**")
        if st.button("🚪 Sair"):
            st.session_state["autenticado"] = False
            st.session_state["usuario"] = None
            st.rerun()

    st.title("🎓 Tutor Acadêmico & Organizador de Estudos")
    st.write("Seu assistente inteligente com RAG, orquestração de matérias, tarefas e visão computacional.")

    aba_chat, aba_visao = st.tabs(["💬 Tutor de Estudos (RAG)", "👁️ Analisador de Exercícios (Visão)"])

    with aba_chat:
        usuario_atual = st.session_state["usuario"]
        historico = carregar_historico_orm(usuario_atual)

        for mensagem in historico:
            with st.chat_message(mensagem["role"]):
                st.markdown(mensagem["content"])

        if pergunta := st.chat_input("Tire uma dúvida de matéria ou consulte suas tarefas..."):
            if not ENDPOINT or not API_KEY or not GPT5_MODEL:
                st.error("Erro de configuração: Variáveis da Azure ausentes.")
                return

            if not client:
                st.error("Erro crítico: Cliente Azure não inicializado.")
                return

            with st.chat_message("user"):
                st.markdown(pergunta)
            salvar_historico_orm(usuario_atual, "user", pergunta)

            with st.status("🧠 Agente organizando bases de estudo...", expanded=True) as status:
                time.sleep(0.4)
                contexto_orquestrado, logs = orquestrar_estudos(pergunta, usuario_atual)
                for log in logs:
                    st.write(log)
                    time.sleep(0.2)
                status.update(label="✅ Orquestração acadêmica concluída!", state="complete", expanded=False)

            prompt_sistema = f"""
Você é um Tutor Acadêmico e Agente de Inteligência Artificial sênior especializado em apoiar estudantes. 
Responda com didática, clareza e precisão utilizando exclusivamente os dados institucionais e de cronograma abaixo:
{contexto_orquestrado}
"""

            mensagens_api = [{"role": "system", "content": prompt_sistema}]
            for m in historico[-6:]:
                mensagens_api.append({"role": m["role"], "content": m["content"]})
            mensagens_api.append({"role": "user", "content": pergunta})

            max_tentativas = 3
            resposta_texto = ""

            for tentativa in range(max_tentativas):
                try:
                    with st.spinner(f"Elaborando explicação... (Tentativa {tentativa+1})"):
                        response = client.chat.completions.create(
                            model=GPT5_MODEL,
                            messages=mensagens_api,
                            max_completion_tokens=800
                        )
                        resposta_texto = response.choices[0].message.content
                        break
                except APIError as e:
                    if getattr(e, 'status_code', None) == 429 or "429" in str(e):
                        if tentativa < max_tentativas - 1:
                            time.sleep(5)
                        else:
                            resposta_texto = "Limite de tokens atingido. Tente novamente em instantes."
                    else:
                        resposta_texto = f"Erro na API Azure: {e}"
                        break
                except Exception as e:
                    if tentativa < max_tentativas - 1:
                        time.sleep(3)
                    else:
                        resposta_texto = f"Erro temporário de conexão: {e}."
                        break

            with st.chat_message("assistant"):
                st.markdown(resposta_texto)
            salvar_historico_orm(usuario_atual, "assistant", resposta_texto)

    with aba_visao:
        st.subheader("Análise de Questões e Imagens Acadêmicas")
        st.write("Envie a foto de uma questão, gráfico ou anotação para o tutor explicar passo a passo.")

        uploaded_file = st.file_uploader("Escolha uma imagem (PNG, JPG, JPEG)", type=["png", "jpg", "jpeg"])

        if uploaded_file is not None:
            st.image(uploaded_file, caption="Exercício enviado", width='stretch')

            if st.button("Explicar Exercício"):
                if not client:
                    st.error("Erro crítico: Cliente Azure não inicializado.")
                    return

                try:
                    with st.spinner("Analisando imagem com Visão Computacional..."):
                        bytes_dados = uploaded_file.getvalue()
                        base64_imagem = base64.b64encode(bytes_dados).decode("utf-8")
                        mime_type = uploaded_file.type

                        response = client.chat.completions.create(
                            model=GPT5_MODEL,
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "text", 
                                            "text": "Você é um professor tutor especialista. Analise esta imagem de caráter acadêmico/estudantil, identifique o problema, questão ou diagrama apresentado e explique detalhadamente a resolução passo a passo para o aluno."
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
                        st.markdown("### Resolução do Tutor:")
                        st.success(resultado_visao)

                except APIError as e:
                    st.error(f"Erro na API do Azure (Visão): {e}")
                except Exception as e:
                    st.error(f"Erro inesperado na visão computacional: {e}")

# --- CONTROLE DE SESSÃO GLOBAL ---
if __name__ == "__main__":
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False

    if not st.session_state["autenticado"]:
        tela_autenticacao()
    else:
        main_app()