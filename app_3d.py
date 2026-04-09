import streamlit as st
import sqlite3
import pandas as pd
import uuid
import os
from datetime import datetime
from fpdf import FPDF
import matplotlib.pyplot as plt
from PIL import Image

# Configuração de pastas
PASTA_PDFS = "orcamentos_pdf"
PASTA_LOGS = "cotacoes_txt"

# Cria as pastas se não existirem
for pasta in [PASTA_PDFS, PASTA_LOGS]:
    if not os.path.exists(pasta):
        os.makedirs(pasta)

# ==============================
# CONFIG DA PÁGINA
# ==============================
st.set_page_config(page_title="3D Print Manager PRO", layout="wide")

# ==============================
# SIDEBAR - CONFIGURAÇÕES
# ==============================
with st.sidebar:
    st.title("⚙️ Configurações Gerais")
    st.subheader("💰 Financeiro")
    TAXA_MEI = st.slider("Imposto (%)", 0.0, 0.2, 0.06, key="taxa")
    META_LUCRO = st.number_input("Meta mensal", value=500.0, key="meta")
    st.divider()
    st.subheader("🧾 Custos")
    C_FILAMENTO_G = st.number_input("Filamento (R$/g)", value=0.12, key="filamento")
    C_HORA_MAQUINA = st.number_input("Máquina (R$/h)", value=1.50, key="maquina")
    C_HORA_TRABALHO = st.number_input("Trabalho (R$/h)", value=6.00, key="trabalho")
    C_FIXO_EMBALAGEM = st.number_input("Custo Fixo", value=2.00, key="fixo")
    FATOR_RISCO = st.slider("Risco (%)", 1.0, 1.5, 1.10, key="risco")

# ==============================
# CONFIGURAÇÕES DO SISTEMA
# ==============================
with st.sidebar.expander("⚙️ Configurações do Sistema"):
    st.subheader("⚠️ Reset do Sistema")
    st.caption("Apaga todos os orçamentos, vendas e fotos do sistema")
    if st.button("🗑️ Limpar todos os dados do sistema"):
        db = sqlite3.connect('sistema_3d_pro.db', check_same_thread=False)
        c = db.cursor()
        c.execute("DELETE FROM orcamentos")
        c.execute("DELETE FROM vendas")
        db.commit()
        # Remove fotos antigas
        if os.path.exists("fotos"):
            for f in os.listdir("fotos"):
                os.remove(os.path.join("fotos", f))
        st.success("✅ Sistema limpo! Todos os orçamentos, vendas e fotos foram apagados.")

# ==============================
# FUNÇÕES (VERSÃO FINAL CONSOLIDADA)
# ==============================

def calcular_custo(peso, h_maq, h_pos):
    """Calcula o custo total considerando insumos, máquina, trabalho e riscos."""
    # Custos Base
    custo_material = (peso * C_FILAMENTO_G) + C_FIXO_EMBALAGEM
    custo_operacional_maq = h_maq * C_HORA_MAQUINA 
    custo_trabalho = h_pos * C_HORA_TRABALHO
    
    # Aplicação do Fator de Risco e Impostos
    base_com_risco = (custo_material + custo_operacional_maq + custo_trabalho) * FATOR_RISCO
    return base_com_risco * (1 + TAXA_MEI)

def calcular_markup_medio(db):
    """Sugere um markup baseado no histórico ou retorna o mínimo de 3.0."""
    try:
        df = pd.read_sql("SELECT valor_final, lucro FROM vendas", db)
        if df.empty:
            return 3.0
        
        df['valor_final'] = pd.to_numeric(df['valor_final'], errors='coerce')
        df['lucro'] = pd.to_numeric(df['lucro'], errors='coerce')
        df['custo'] = df['valor_final'] - df['lucro']
        
        # Filtra custos zerados e calcula média
        df = df[df['custo'] > 0]
        media_historica = (df['valor_final'] / df['custo']).mean()
        
        # Regra de Negócio: Nunca sugerir menos que 3.0
        return round(max(media_historica, 3.0), 2)
    except:
        return 3.0

def gerar_pdf(nome, valor, id_prod, link):
    """Gera um PDF de orçamento simples para um único produto."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "ORÇAMENTO DE IMPRESSÃO 3D", ln=True, align="C")
    pdf.ln(10)
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Produto: {nome}", ln=True)
    pdf.cell(0, 10, f"ID de Referência: {id_prod}", ln=True)
    pdf.cell(0, 10, f"Valor Final: R$ {valor:.2f}", ln=True)
    if link:
        pdf.ln(5)
        pdf.multi_cell(0, 10, f"Link do Modelo: {link}")
    path = f"orcamento_{id_prod}.pdf"
    pdf.output(path)
    return path

def gerar_catalogo_bytes(df):
    """Gera o catálogo completo com fotos e retorna os bytes para download."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    for _, r in df.iterrows():
        pdf.add_page()
        nome = str(r.get('nome', 'Sem nome')).upper()
        preco = float(r.get('venda_sugerida', 0))
        foto = r.get('foto_path', '')
        
        pdf.set_font("Arial", "B", 18)
        pdf.cell(0, 15, nome, ln=True, align="C")
        pdf.ln(5)
        
        if foto and os.path.exists(foto):
            try:
                full_path = os.path.abspath(foto)
                pdf.image(full_path, x=45, w=120)
                pdf.ln(10)
            except:
                pdf.set_font("Arial", "I", 10)
                pdf.cell(0, 10, "(Erro ao carregar imagem)", ln=True, align="C")
        else:
            pdf.ln(40)
            pdf.cell(0, 10, "FOTO EM BREVE", ln=True, align="C")

        pdf.set_y(-40)
        pdf.set_font("Arial", "B", 22)
        pdf.set_text_color(46, 125, 50) # Verde
        pdf.cell(0, 15, f"VALOR: R$ {preco:.2f}", ln=True, align="C")
        pdf.set_text_color(0, 0, 0)
    
    # CORREÇÃO DO ERRO BYTEARRAY/ENCODE
    pdf_out = pdf.output(dest='S')
    if isinstance(pdf_out, str):
        return pdf_out.encode('latin-1', errors='replace')
    return bytes(pdf_out)

# ==============================
# BANCO DE DADOS
# ==============================
def add_column_if_not_exists(cursor, table, column, col_type):
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise

def init_db():
    conn = sqlite3.connect('sistema_3d_pro.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS orcamentos (id TEXT PRIMARY KEY, nome TEXT)')
    add_column_if_not_exists(c,"orcamentos","link","TEXT")
    add_column_if_not_exists(c,"orcamentos","peso","REAL")
    add_column_if_not_exists(c,"orcamentos","h_maq","REAL")
    add_column_if_not_exists(c,"orcamentos","h_pos","REAL")
    add_column_if_not_exists(c,"orcamentos","custo_total","REAL")
    add_column_if_not_exists(c,"orcamentos","venda_sugerida","REAL")
    add_column_if_not_exists(c,"orcamentos","markup","REAL")
    add_column_if_not_exists(c,"orcamentos","foto_path","TEXT")
    add_column_if_not_exists(c,"orcamentos","vendido","INTEGER DEFAULT 0")
    c.execute('''
        CREATE TABLE IF NOT EXISTS vendas (
            id_venda INTEGER PRIMARY KEY AUTOINCREMENT,
            id_prod TEXT,
            valor_final REAL,
            lucro REAL,
            data TEXT
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_orcamentos_vendido ON orcamentos(vendido)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_vendas_data ON vendas(data)')
    conn.commit()
    return conn

db = init_db()

# ==============================
# SIDEBAR MENU
# ==============================
with st.sidebar:
    st.title("🚀 3D PRO PREMIUM")
    menu = st.radio("Menu", ["Dashboard","Orçamento","Venda","Catálogo","Prospecção","Cotação"])
    markup_global = st.slider("Markup Global",1.0,5.0,2.5,0.1)
    
# ==============================
# DASHBOARD (VERSÃO REVISADA)
# ==============================
if menu == "Dashboard":
    st.title("📊 Dashboard Premium Inteligente")
    
    # Busca segura de dados
    try:
        df_dash = pd.read_sql("SELECT * FROM vendas", db)
    except:
        df_dash = pd.DataFrame()

    if df_dash.empty:
        st.info("ℹ️ Nenhuma venda registrada ainda. Os gráficos aparecerão após a primeira venda.")
    else:
        # Tratamento de dados numéricos e datas
        df_dash['valor_final'] = pd.to_numeric(df_dash['valor_final'], errors='coerce')
        df_dash['lucro'] = pd.to_numeric(df_dash['lucro'], errors='coerce')
        df_dash['data'] = pd.to_datetime(df_dash['data'], dayfirst=True, errors='coerce')
        df_dash = df_dash.dropna(subset=['valor_final', 'lucro'])

        # Cálculos de métricas de negócio
        df_dash['custo'] = df_dash['valor_final'] - df_dash['lucro']
        # Evita divisão por zero no markup
        df_dash['markup'] = df_dash.apply(lambda x: x['valor_final'] / x['custo'] if x['custo'] > 0 else 0, axis=1)
        
        # Filtro de Período
        periodo = st.selectbox("Filtrar Visão", ["Total", "Este Mês", "Hoje"])
        hoje = pd.Timestamp.today()
        
        if periodo == "Hoje":
            df_dash = df_dash[df_dash['data'].dt.date == hoje.date()]
        elif periodo == "Este Mês":
            df_dash = df_dash[(df_dash['data'].dt.month == hoje.month) & (df_dash['data'].dt.year == hoje.year)]
            
        # Agregações
        fat = df_dash['valor_final'].sum()
        lucro_total = df_dash['lucro'].sum()
        qtd = len(df_dash)
        ticket = fat / qtd if qtd else 0
        margem = (lucro_total / fat * 100) if fat else 0
        markup_medio = df_dash['markup'].mean() if not df_dash.empty else 0
        
        # Métrica Visual (KPIs)
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("💰 Faturamento", f"R$ {fat:.2f}")
        c2.metric("📈 Lucro", f"R$ {lucro_total:.2f}")
        c3.metric("🧾 Vendas", qtd)
        c4.metric("🎯 Ticket", f"R$ {ticket:.2f}")
        c5.metric("📊 Margem", f"{margem:.1f}%")
        
        # Indicador de Saúde da Regra de Negócio (Markup 3.0x)
        delta_saude = "Saudável" if markup_medio >= 3.0 else "Abaixo da Meta"
        c6.metric("🧠 Markup Médio", f"{markup_medio:.2f}x", 
                  delta=delta_saude, 
                  delta_color="normal" if markup_medio >= 3.0 else "inverse")
        
        st.divider()

        # Gráficos
        col_g1, col_g2 = st.columns(2)
        
        with col_g1:
            grp = df_dash.groupby(df_dash['data'].dt.date)['valor_final'].sum()
            if not grp.empty:
                fig, ax = plt.subplots(figsize=(8, 4))
                ax.plot(grp.index, grp.values, marker='o', color='#4CAF50')
                ax.set_title("Faturamento Diário")
                plt.xticks(rotation=45)
                st.pyplot(fig)

        with col_g2:
            lucro_prod = df_dash.groupby("id_prod")['lucro'].sum().sort_values(ascending=False).head(10)
            if not lucro_prod.empty:
                fig2, ax2 = plt.subplots(figsize=(8, 4))
                lucro_prod.plot(kind='bar', color='#2196F3', ax=ax2)
                ax2.set_title("Lucro por Produto")
                st.pyplot(fig2)

# ==============================
# ORÇAMENTO (COM MODO LOTE + IA)
# ==============================
elif menu == "Orçamento":
    st.title("🧠 Orçamento Inteligente")
    
    # =============================
    # IDENTIFICAÇÃO
    # =============================
    col_n, col_l = st.columns(2)
    nome = col_n.text_input("Nome do Produto")
    link = col_l.text_input("Link (MakerWorld/STL)")
    
    modo = st.radio("Modo de Cálculo", ["Peça Única", "Produção em Lote"])
    
    st.divider()
    
    # =============================
    # INPUTS
    # =============================
    if modo == "Peça Única":

        peso = st.number_input("Peso da peça (g)", min_value=0.1, value=10.0)

        col_maq, col_pos = st.columns(2)
        with col_maq:
            st.subheader("⏱️ Tempo de Máquina")
            h_maq_h = st.number_input("Horas", min_value=0, key="h_m1")
            h_maq_m = st.number_input("Minutos", min_value=0, max_value=59, key="m_m1")
        with col_pos:
            st.subheader("🛠️ Tempo de Trabalho")
            h_pos_h = st.number_input("Horas", min_value=0, key="h_t1")
            h_pos_m = st.number_input("Minutos", min_value=0, max_value=59, key="m_t1")

        h_maq = h_maq_h + (h_maq_m / 60)
        h_pos = h_pos_h + (h_pos_m / 60)

        custo_total = calcular_custo(peso, h_maq, h_pos)
        custo_unitario = custo_total
        qtd_lote = 1

    else:
        qtd_lote = st.number_input("Quantidade no lote", min_value=2, value=10)

        peso_total = st.number_input("Peso total do lote (g)", min_value=0.1, value=50.0)

        col_maq, col_pos = st.columns(2)
        with col_maq:
            st.subheader("⏱️ Tempo de Máquina (lote)")
            h_maq_h = st.number_input("Horas", min_value=0, key="h_m2")
            h_maq_m = st.number_input("Minutos", min_value=0, max_value=59, key="m_m2")
        with col_pos:
            st.subheader("🛠️ Tempo de Trabalho (lote)")
            h_pos_h = st.number_input("Horas", min_value=0, key="h_t2")
            h_pos_m = st.number_input("Minutos", min_value=0, max_value=59, key="m_t2")

        h_maq = h_maq_h + (h_maq_m / 60)
        h_pos = h_pos_h + (h_pos_m / 60)

        custo_total = calcular_custo(peso_total, h_maq, h_pos)
        custo_unitario = custo_total / qtd_lote

    # =============================
    # FOTO
    # =============================
    foto = st.file_uploader("📸 Upload da Foto do Modelo", type=['png','jpg','jpeg'])

    # =============================
    # 🤖 PRECIFICAÇÃO INTELIGENTE
    # =============================
    st.divider()

    markups_simulacao = [2.5, 3.0, 3.5, 4.0, 5.0]

    def chance_venda(markup):
        if markup <= 3.0:
            return 1.0
        elif markup <= 3.5:
            return 0.85
        elif markup <= 4.0:
            return 0.7
        else:
            return 0.5

    dados = []

    for m in markups_simulacao:
        preco_unit = custo_unitario * m
        lucro_unit = preco_unit - custo_unitario

        lucro_total_sim = lucro_unit * qtd_lote
        score = lucro_total_sim * chance_venda(m)

        dados.append({
            "Markup": m,
            "Preço Unitário": preco_unit,
            "Lucro Unitário": lucro_unit,
            "Lucro Total": lucro_total_sim,
            "Score": score
        })

    df_preco = pd.DataFrame(dados)

    df_seguro = df_preco[df_preco["Markup"] >= 3.0]

    if not df_seguro.empty:
        melhor = df_seguro.sort_values("Score", ascending=False).iloc[0]
    else:
        melhor = df_preco.sort_values("Score", ascending=False).iloc[0]

    markup_auto = melhor["Markup"]
    preco_unitario = melhor["Preço Unitário"]
    lucro_unitario = melhor["Lucro Unitário"]

    preco_total = preco_unitario * qtd_lote
    lucro_total = lucro_unitario * qtd_lote

    # =============================
    # VISUAL
    # =============================
    c1, c2 = st.columns(2)

    with c1:
        st.metric("💰 Custo Unitário", f"R$ {custo_unitario:.2f}")

    with c2:
        st.metric("💸 Preço Inteligente", f"R$ {preco_unitario:.2f}")

    st.success(f"🤖 Markup ideal: {markup_auto}x")
    st.write(f"📈 Lucro Unitário: R$ {lucro_unitario:.2f}")

    if modo == "Produção em Lote":
        st.info(f"📦 Lote com {qtd_lote} unidades")
        col_l1, col_l2 = st.columns(2)
        col_l1.metric("💰 Faturamento", f"R$ {preco_total:.2f}")
        col_l2.metric("📈 Lucro Total", f"R$ {lucro_total:.2f}")

    # =============================
    # AJUSTE MANUAL (OPCIONAL)
    # =============================
    st.divider()
    st.subheader("⚙️ Ajuste fino (opcional)")

    markup_manual = st.slider("Ajustar markup", 1.0, 5.0, float(markup_auto), 0.1)

    preco_unitario = custo_unitario * markup_manual
    lucro_unitario = preco_unitario - custo_unitario
    preco_total = preco_unitario * qtd_lote
    lucro_total = lucro_unitario * qtd_lote

    # =============================
    # SALVAR
    # =============================
    if st.button("💾 Salvar Orçamento e Gerar PDF", use_container_width=True):
        if not nome:
            st.error("❌ Por favor, insira o nome do produto.")
        else:
            id_f = uuid.uuid4().hex[:8]
            path = ""

            if foto:
                os.makedirs("fotos", exist_ok=True)
                path = f"fotos/{id_f}.png"
                img = Image.open(foto)
                img.thumbnail((800, 800))
                img.save(path)

            db.execute("""
                INSERT INTO orcamentos 
                (id, nome, link, peso, h_maq, h_pos, custo_total, venda_sugerida, markup, foto_path, vendido)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                id_f,
                nome,
                link,
                peso if modo == "Peça Única" else peso_total,
                h_maq,
                h_pos,
                custo_total,
                preco_unitario,
                markup_manual,
                path
            ))
            db.commit()

            st.balloons()
            st.success("✅ Orçamento salvo com sucesso!")

            pdf_path = gerar_pdf(nome, preco_unitario, id_f, link)
            with open(pdf_path, "rb") as f:
                st.download_button("📄 Baixar Orçamento PDF", f, file_name=f"Orcamento_{nome}.pdf")
                
# ==============================
# VENDA (VERSÃO REVISADA)
# ==============================
elif menu == "Venda":
    # Busca apenas orçamentos não vendidos de forma segura
    try:
        df_venda = pd.read_sql("SELECT * FROM orcamentos WHERE vendido=0", db)
    except:
        df_venda = pd.DataFrame()
    
    if df_venda.empty:
        st.warning("⚠️ Nenhum orçamento disponível para venda. Cadastre um novo orçamento primeiro.")
    else:
        st.title("💵 Registrar Venda")
        
        # Seleção do Produto
        opcoes = df_venda.apply(lambda row: f"{row['id']} - {row['nome']}", axis=1).tolist()
        escolha = st.selectbox("Selecione o Orçamento", opcoes)
        id_sel = escolha.split(" - ")[0]
        
        # Filtra os dados do item selecionado
        dados = df_venda[df_venda['id'] == id_sel].iloc[0]

        st.divider()
        
        col_img, col_det = st.columns([1, 2])
        
        foto_path = dados.get('foto_path', '')
        if foto_path and os.path.exists(foto_path):
            col_img.image(foto_path, use_container_width=True)
        else:
            col_img.info("🖼️ Sem Foto")
        
        with col_det:
            st.subheader(f"📦 {dados['nome']}")
            st.write(f"**Custo de Produção:** R$ {dados['custo_total']:.2f}")
            st.write(f"**Sugestão (Markup {dados['markup']:.1f}x):** R$ {dados['venda_sugerida']:.2f}")
            
            # Inputs de fechamento
            valor_final = st.number_input("Valor Final de Venda (R$)", value=float(dados['venda_sugerida']), step=1.0, key="val_venda")
            qtd_venda = st.number_input("Quantidade de Peças", min_value=1, value=1, step=1, key="qtd_venda")
            
            # Cálculo de Markup Real do fechamento
            custo_unitario = float(dados['custo_total'])
            markup_real = valor_final / custo_unitario if custo_unitario > 0 else 0
            lucro_total = (valor_final - custo_unitario) * qtd_venda
            
            # Feedback da Regra de Negócio
            if markup_real < 3.0:
                st.error(f"⚠️ **Markup Real: {markup_real:.2f}x** - Abaixo da meta de segurança!")
            else:
                st.success(f"✅ **Markup Real: {markup_real:.2f}x** - Venda saudável.")

        # Botão de confirmação
        if st.button("🚀 Confirmar e Finalizar Venda", use_container_width=True):
            try:
                data_atual = datetime.now().strftime("%d/%m/%Y")
                
                # Registra na tabela de vendas
                for _ in range(qtd_venda):
                    db.execute(
                        "INSERT INTO vendas (id_prod, valor_final, lucro, data) VALUES (?,?,?,?)",
                        (id_sel, valor_final, valor_final - custo_unitario, data_atual)
                    )
                
                # Marca como vendido no cadastro de orçamentos
                db.execute("UPDATE orcamentos SET vendido=1 WHERE id=?", (id_sel,))
                db.commit()
                
                st.balloons()
                st.success(f"✅ Venda registrada! Lucro total: R$ {lucro_total:.2f}")
                st.rerun() # Atualiza a tela para o item sumir da lista de pendentes
            except Exception as e:
                st.error(f"Erro ao registrar venda: {e}")

# ==============================
# CATÁLOGO (REVISADO)
# ==============================
elif menu == "Catálogo":
    st.title("📋 Catálogo de Produtos")
    
    try:
        # Busca todos os orçamentos para montar a vitrine
        df_cat = pd.read_sql("SELECT * FROM orcamentos", db)
    except:
        df_cat = pd.DataFrame()
    
    if df_cat.empty:
        st.warning("⚠️ O banco de dados está vazio. Cadastre orçamentos primeiro.")
    else:
        st.subheader("🎒 Montar Vitrine")
        opcoes = [f"{row['id']} - {row['nome']}" for _, row in df_cat.iterrows()]
        selecionados = st.multiselect("Escolha os produtos para o catálogo:", options=opcoes, default=opcoes)
        
        # Filtra apenas os IDs selecionados
        ids_selecionados = [x.split(" - ")[0] for x in selecionados]
        df_para_catalogo = df_cat[df_cat['id'].isin(ids_selecionados)]

        if st.button("📄 Gerar Catálogo PDF"):
            with st.spinner("Compilando imagens e preços..."):
                try:
                    # Chama a função que corrigimos e movemos para o topo
                    pdf_bytes = gerar_catalogo_bytes(df_para_catalogo)
                    st.download_button(
                        "🖨️ Clique para Baixar o Catálogo", 
                        data=pdf_bytes, 
                        file_name=f"catalogo_cria3d_{datetime.now().strftime('%d_%m')}.pdf", 
                        mime="application/pdf"
                    )
                except Exception as e:
                    st.error(f"Erro ao gerar PDF: {e}")

        st.divider()
        
        # Visualização em Grid
        st.subheader("👀 Visualização da Vitrine")
        for _, r in df_para_catalogo.iterrows():
            with st.container():
                c1, c2 = st.columns([1, 2])
                foto_path = r.get('foto_path', '')
                if foto_path and os.path.exists(foto_path):
                    c1.image(foto_path, use_container_width=True)
                else:
                    c1.warning("🖼️ (Sem Foto)")
                
                with c2:
                    st.subheader(str(r.get('nome', 'Sem Nome')).upper())
                    st.title(f"R$ {float(r.get('venda_sugerida', 0)):.2f}")
                    st.caption(f"Ref ID: {r['id']}")
            st.divider()
   
# ==============================
# PROSPECÇÃO
# ==============================
elif menu == "Prospecção":
    st.title("🔍 Prospecção de Markup Inteligente")
    
    # 1. Busca dados do banco de forma segura
    try:
        df_pros = pd.read_sql("SELECT * FROM orcamentos", db)
    except Exception as e:
        st.error(f"Erro ao acessar banco de dados: {e}")
        df_pros = pd.DataFrame()

    # 2. Verifica se há orçamentos salvos
    if df_pros.empty:
        st.warning("⚠️ **Nenhum orçamento encontrado!**")
        st.info("Para simular lucros, você precisa primeiro cadastrar e **SALVAR** um item na aba **Orçamento**.")
    else:
        # 3. Define os markups da regra de negócio (Piso de 3.0x)
        markups = [3.0, 3.5, 4.0]

        # 4. Cálculos de projeção
        for m in markups:
            df_pros[f'venda_{m}x'] = df_pros['custo_total'] * m
            df_pros[f'lucro_{m}x'] = df_pros[f'venda_{m}x'] - df_pros['custo_total']

        # 5. Tabela Comparativa
        st.subheader("📊 Tabela de Cenários")
        cols = ['nome', 'custo_total'] + [f'venda_{m}x' for m in markups]
        st.dataframe(df_pros[cols].round(2), use_container_width=True)

        st.divider()

        # 6. Simulação de Demanda
        st.subheader("📦 Simulação de Demanda Mensal")
        demanda_inputs = {}
        cols_demanda = st.columns(len(markups))
        for i, m in enumerate(markups):
            demanda_inputs[m] = cols_demanda[i].number_input(
                f"Qtd venda ({m}x)", min_value=0, value=10, key=f"input_pros_{m}"
            )

        # 7. Resultados Consolidados
        st.subheader("💰 Resultados da Simulação")
        resultados = []
        for m in markups:
            faturamento = (df_pros[f'venda_{m}x'] * demanda_inputs[m]).sum()
            lucro_total = (df_pros[f'lucro_{m}x'] * demanda_inputs[m]).sum()
            resultados.append({"markup": m, "lucro": lucro_total, "faturamento": faturamento})

        cols_res = st.columns(len(markups))
        melhor = max(resultados, key=lambda x: x['lucro'])
        
        for i, r in enumerate(resultados):
            destaque = "🏆 MELHOR" if r == melhor else ""
            cols_res[i].metric(
                label=f"{r['markup']}x {destaque}",
                value=f"R$ {r['lucro']:.2f}",
                delta=f"Fat. R$ {r['faturamento']:.2f}"
            )

#==============================
# COTAÇÃO COM MODO LOTE + IA
# ==============================
elif menu == "Cotação":

    st.title("📝 Cotação Rápida")

    modo = st.radio("Modo de Cálculo", ["Peça Única", "Produção em Lote"])

    # =============================
    # INPUTS
    # =============================
    if modo == "Peça Única":

        peso = st.number_input("Peso (g)", min_value=0.1, value=10.0)

        h_maq = st.number_input("Horas máquina", min_value=0.0, value=1.0)
        h_pos = st.number_input("Horas trabalho", min_value=0.0, value=0.25)

        custo_total = calcular_custo(peso, h_maq, h_pos)
        custo_unitario = custo_total
        qtd_lote = 1

    else:
        qtd_lote = st.number_input("Qtd lote", min_value=2, value=10)

        peso_total = st.number_input("Peso total (g)", min_value=0.1, value=50.0)

        h_maq = st.number_input("Horas máquina lote", min_value=0.0, value=2.0)
        h_pos = st.number_input("Horas trabalho lote", min_value=0.0, value=0.5)

        custo_total = calcular_custo(peso_total, h_maq, h_pos)
        custo_unitario = custo_total / qtd_lote

    # =============================
    # SIMULAÇÃO
    # =============================
    markups = [2.5, 3.0, 3.5, 4.0, 5.0]
    dados_cotacao = []

    for m in markups:
        preco_unit = custo_unitario * m
        lucro_unit = preco_unit - custo_unitario
        lucro_total = lucro_unit * qtd_lote

        dados_cotacao.append({
            "Markup": m,
            "Preço Unitário": round(preco_unit, 2),
            "Lucro Total": round(lucro_total, 2)
        })

    df_cotacao = pd.DataFrame(dados_cotacao)

    st.dataframe(df_cotacao)

    # =============================
    # 🤖 IA (EQUILÍBRIO CLIENTE x LUCRO)
    # =============================
    def chance_venda(markup):
        if markup <= 3.0: return 1.0
        elif markup <= 3.5: return 0.85
        elif markup <= 4.0: return 0.7
        else: return 0.5

    df_cotacao["Chance"] = df_cotacao["Markup"].apply(chance_venda)
    df_cotacao["Score"] = df_cotacao["Lucro Total"] * df_cotacao["Chance"]

    melhor = df_cotacao.sort_values("Score", ascending=False).iloc[0]

    markup_auto = melhor["Markup"]
    preco_auto = melhor["Preço Unitário"]
    lucro_auto = melhor["Lucro Total"]

    st.success(f"🤖 Melhor equilíbrio: {markup_auto}x")
    st.info(f"💸 Preço sugerido: R$ {preco_auto:.2f}")

    # =============================
    # ⚖️ LOTE vs PEÇA
    # =============================
    if modo == "Produção em Lote" and qtd_lote > 1:

        tempo_total = h_maq + h_pos

        lucro_hora_lote = lucro_auto / tempo_total if tempo_total > 0 else 0

        custo_simples = calcular_custo(
            custo_total / qtd_lote,
            h_maq / qtd_lote,
            h_pos / qtd_lote
        )

        lucro_simples = (custo_simples * markup_auto) - custo_simples
        lucro_hora_simples = lucro_simples / tempo_total if tempo_total > 0 else 0

        st.subheader("⚖️ Comparação")

        col1, col2 = st.columns(2)
        col1.metric("Peça Única (R$/h)", f"{lucro_hora_simples:.2f}")
        col2.metric("Lote (R$/h)", f"{lucro_hora_lote:.2f}")

        if lucro_hora_lote > lucro_hora_simples:
            st.success("🚀 Melhor produzir em LOTE")
        else:
            st.warning("⚠️ Melhor peça única")

    # =============================
    # RELATÓRIO
    # =============================
    txt = f"""
Modo: {modo}
Qtd: {qtd_lote}

Custo Unitário: R$ {custo_unitario:.2f}
Custo Total: R$ {custo_total:.2f}

Markup: {markup_auto}x
Preço: R$ {preco_auto:.2f}
"""

    st.download_button("📄 Baixar", txt)

# ==============================
# RODAPÉ (FOOTER)
# ==============================
st.sidebar.divider()
st.sidebar.caption("🚀 **3D Print Manager PRO**")
st.sidebar.write("Desenvolvido por **Cria3d (Marcelo Prado)**")	