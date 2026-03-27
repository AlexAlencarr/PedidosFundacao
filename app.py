from flask import Flask, render_template, request, redirect, url_for, session, make_response, jsonify
import sqlite3
import json
import os
import unicodedata
import csv
import io
from fpdf import FPDF
from datetime import datetime
import pytz

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "escola.db")

LISTA_PROFESSORES = [
    "Piedade", "Crislaine", "Ianka", "Ivaneide", "Camila",
    "Talita", "Maiara", "Clara", "Priscilla", "Luciana",
    "Marlise", "Carla", "Aline", "Verônica"
]

def normalizar_texto(texto):
    if not texto: return ""
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower().strip()

def get_data_brasilia():
    fuso_br = pytz.timezone('America/Sao_Paulo')
    return datetime.now(fuso_br).strftime('%Y-%m-%d %H:%M:%S')

def formatar_data_br(data_iso):
    try:
        data_obj = datetime.strptime(data_iso, '%Y-%m-%d %H:%M:%S')
        return data_obj.strftime('%d/%m/%Y %H:%M')
    except:
        return data_iso

def init_db():
    if not os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE materiais (id INTEGER PRIMARY KEY, nome TEXT, unidade TEXT)''')
        cursor.execute('''CREATE TABLE pedidos (
                            id INTEGER PRIMARY KEY,
                            professor TEXT,
                            data_pedido TIMESTAMP)''')

        cursor.execute('''CREATE TABLE itens_pedido (
                            id INTEGER PRIMARY KEY,
                            pedido_id INTEGER,
                            material_nome TEXT,
                            quantidade REAL,
                            quantidade_aprovada REAL DEFAULT 0,
                            status TEXT DEFAULT 'Pendente',
                            adicionado_por TEXT DEFAULT 'professor',
                            FOREIGN KEY(pedido_id) REFERENCES pedidos(id))''')

        # Tabela do Catálogo
        cursor.execute('''CREATE TABLE IF NOT EXISTS catalogo_produtos (
                            id INTEGER PRIMARY KEY,
                            nome TEXT UNIQUE)''')

        conn.commit()
        conn.close()

# --- ROTAS DE GESTÃO DO CATÁLOGO (NOVO) ---

@app.route('/importar_csv', methods=['POST'])
def importar_csv():
    if session.get('user') != 'admin': return redirect(url_for('index'))

    if 'arquivo_csv' not in request.files:
        return "Nenhum arquivo enviado."

    arquivo = request.files['arquivo_csv']
    if arquivo.filename == '':
        return "Nenhum arquivo selecionado."

    if arquivo:
        # Lê o arquivo CSV
        stream = io.StringIO(arquivo.stream.read().decode("utf-8"), newline=None)
        csv_input = csv.reader(stream)

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        contagem = 0
        for row in csv_input:
            if row:
                # Pega a primeira coluna do CSV (Nome do Produto)
                produto = row[0].strip()
                if produto:
                    try:
                        cursor.execute("INSERT INTO catalogo_produtos (nome) VALUES (?)", (produto,))
                        contagem += 1
                    except sqlite3.IntegrityError:
                        pass # Ignora duplicados

        conn.commit()
        conn.close()

    return redirect(url_for('painel_coordenacao', aba='catalogo'))

@app.route('/gerenciar_catalogo', methods=['POST'])
def gerenciar_catalogo():
    if session.get('user') != 'admin': return redirect(url_for('index'))

    acao = request.form.get('acao')
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if acao == 'adicionar':
        nome = request.form.get('nome_produto')
        if nome:
            try:
                cursor.execute("INSERT INTO catalogo_produtos (nome) VALUES (?)", (nome,))
            except sqlite3.IntegrityError:
                pass # Já existe

    elif acao == 'renomear':
        id_prod = request.form.get('id_produto')
        novo_nome = request.form.get('novo_nome')
        if id_prod and novo_nome:
            try:
                cursor.execute("UPDATE catalogo_produtos SET nome = ? WHERE id = ?", (novo_nome, id_prod))
            except sqlite3.IntegrityError:
                pass

    elif acao == 'deletar':
        id_prod = request.form.get('id_produto')
        cursor.execute("DELETE FROM catalogo_produtos WHERE id = ?", (id_prod,))

    conn.commit()
    conn.close()
    return redirect(url_for('painel_coordenacao', aba='catalogo'))

@app.route('/api/produtos')
def api_produtos():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT nome FROM catalogo_produtos ORDER BY nome ASC")
    produtos = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify(produtos)

# --- ROTAS BÁSICAS ---
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario_input = request.form['usuario']
    senha_input = request.form['senha']
    erro = None
    if usuario_input == 'admin':
        if senha_input == 'admin':
            session['user'] = 'admin'
            return redirect(url_for('painel_coordenacao'))
        else:
            erro = "Senha de administrador incorreta."
    else:
        usuario_normalizado = normalizar_texto(usuario_input)
        professor_encontrado = None
        for prof_real in LISTA_PROFESSORES:
            if normalizar_texto(prof_real) == usuario_normalizado:
                professor_encontrado = prof_real
                break
        if professor_encontrado:
            if senha_input == '123':
                session['user'] = professor_encontrado
                return redirect(url_for('painel_professor'))
            else:
                erro = "Senha incorreta."
        else:
            erro = "Usuário não encontrado."
    return render_template('login.html', erro=erro)

@app.route('/professor')
def painel_professor():
    if 'user' not in session: return redirect(url_for('index'))
    professor = session['user']
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, data_pedido FROM pedidos WHERE professor = ? ORDER BY id DESC", (professor,))
    meus_pedidos_raw = cursor.fetchall()

    historico = []
    for ped in meus_pedidos_raw:
        cursor.execute("SELECT id, material_nome, quantidade, status, quantidade_aprovada, adicionado_por FROM itens_pedido WHERE pedido_id = ?", (ped[0],))
        itens = cursor.fetchall()
        pode_editar = all(item[3] == 'Pendente' for item in itens)
        todos_cancelados = all(item[3] == 'Cancelado' for item in itens) and len(itens) > 0

        # Formata para exibir sem .0
        itens_formatados = []
        for i in itens:
            qtd_fmt = f"{i[2]:g}"
            qtd_apr_fmt = f"{i[4]:g}"
            itens_formatados.append((i[0], i[1], qtd_fmt, i[3], qtd_apr_fmt, i[5]))

        historico.append({
            'id': ped[0],
            'data': formatar_data_br(ped[1]),
            'itens': itens_formatados,
            'pode_editar': pode_editar,
            'todos_cancelados': todos_cancelados
        })
    conn.close()
    return render_template('professor.html', usuario=professor, historico=historico)

@app.route('/solicitar', methods=['POST'])
def solicitar():
    if 'user' not in session: return redirect(url_for('index'))
    professor = session['user']
    dados_json = request.form['conteudo_pedido']
    itens = json.loads(dados_json)
    if not itens: return "Pedido vazio"

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # --- VALIDAÇÃO RÍGIDA: Produto TEM que existir no catálogo ---
    cursor.execute("SELECT nome FROM catalogo_produtos")
    produtos_validos = {row[0] for row in cursor.fetchall()}

    for item in itens:
        if item['material'] not in produtos_validos:
            conn.close()
            return f"ERRO: O produto '{item['material']}' não consta no catálogo oficial. O pedido foi cancelado."

    # Se passou, salva tudo
    data_br = get_data_brasilia()
    cursor.execute("INSERT INTO pedidos (professor, data_pedido) VALUES (?, ?)", (professor, data_br))
    pedido_id = cursor.lastrowid
    for item in itens:
        cursor.execute("INSERT INTO itens_pedido (pedido_id, material_nome, quantidade) VALUES (?, ?, ?)",
                       (pedido_id, item['material'], float(item['quantidade'])))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/cancelar_pedido/<int:id>')
def cancelar_pedido(id):
    if 'user' not in session: return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE itens_pedido SET status = 'Cancelado', quantidade_aprovada = 0 WHERE pedido_id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/deletar_item/<int:item_id>')
def deletar_item(item_id):
    if 'user' not in session: return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE itens_pedido SET status = 'Cancelado', quantidade_aprovada = 0 WHERE id = ? AND status = 'Pendente'", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/editar_qtd_item', methods=['POST'])
def editar_qtd_item():
    if 'user' not in session: return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE itens_pedido SET quantidade = ? WHERE id = ? AND status = 'Pendente'", (float(request.form['nova_qtd']), request.form['item_id']))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

# --- ROTAS DA COORDENAÇÃO ---

@app.route('/coordenacao')
def painel_coordenacao():
    if session.get('user') != 'admin': return redirect(url_for('index'))

    # Controle de Abas (Pedidos vs Catálogo)
    aba_ativa = request.args.get('aba', 'pedidos')

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Dados para aba Catálogo
    cursor.execute("SELECT id, nome FROM catalogo_produtos ORDER BY nome ASC")
    catalogo = cursor.fetchall()

    # Dados para aba Pedidos (Filtros)
    filtro_prof = request.args.get('professor', '')
    data_ini = request.args.get('data_ini', '')
    data_fim = request.args.get('data_fim', '')
    filtro_status = request.args.get('visualizacao', 'pendentes')

    query = "SELECT * FROM pedidos WHERE 1=1"
    params = []

    if filtro_prof:
        query += " AND professor = ?"
        params.append(filtro_prof)
    if data_ini:
        query += " AND date(data_pedido) >= ?"
        params.append(data_ini)
    if data_fim:
        query += " AND date(data_pedido) <= ?"
        params.append(data_fim)

    query += " ORDER BY id DESC"

    cursor.execute(query, params)
    todos_pedidos = cursor.fetchall()

    lista_final = []
    for ped in todos_pedidos:
        cursor.execute("SELECT id, material_nome, quantidade, status, quantidade_aprovada, adicionado_por FROM itens_pedido WHERE pedido_id = ?", (ped[0],))
        itens = cursor.fetchall()

        # Lógica de Status Geral
        todos_itens_cancelados = all(item[3] == 'Cancelado' for item in itens)
        tem_pendente = any(item[3] == 'Pendente' for item in itens)
        if todos_itens_cancelados: status_geral = 'Cancelado'
        elif tem_pendente: status_geral = 'Pendente'
        else: status_geral = 'Concluido'

        adicionar = False
        if filtro_status == 'todos': adicionar = True
        elif filtro_status == 'pendentes' and status_geral == 'Pendente': adicionar = True
        elif filtro_status == 'concluidos' and status_geral == 'Concluido': adicionar = True
        elif filtro_status == 'cancelados' and status_geral == 'Cancelado': adicionar = True

        if adicionar:
            # Formatação
            itens_formatados = []
            for i in itens:
                qtd_fmt = f"{i[2]:g}"
                qtd_apr_fmt = f"{i[4]:g}"
                itens_formatados.append((i[0], i[1], qtd_fmt, i[3], qtd_apr_fmt, i[5]))

            lista_final.append({
                'id': ped[0],
                'professor': ped[1],
                'data': formatar_data_br(ped[2]),
                'status_geral': status_geral,
                'itens': itens_formatados
            })

    conn.close()
    return render_template('coordenacao.html',
                           pedidos=lista_final,
                           lista_professores=LISTA_PROFESSORES,
                           filtros=request.args,
                           catalogo=catalogo,
                           aba_ativa=aba_ativa)

@app.route('/atualizar_pedido', methods=['POST'])
def atualizar_pedido():
    if session.get('user') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for key, value in request.form.items():
        if key.startswith('status_'):
            item_id = key.replace('status_', '')
            status_escolhido = value
            qtd_aprovada = float(request.form.get(f"qtd_aprov_{item_id}", 0))

            if status_escolhido == 'Reprovado':
                qtd_aprovada = 0

            cursor.execute("UPDATE itens_pedido SET status = ?, quantidade_aprovada = ? WHERE id = ?", (value, qtd_aprovada, item_id))

    conn.commit()
    conn.close()
    return redirect(url_for('painel_coordenacao'))

@app.route('/adicionar_itens_coordenacao', methods=['POST'])
def adicionar_itens_coordenacao():
    if session.get('user') != 'admin': return redirect(url_for('index'))

    pedido_id = request.form['pedido_id']
    materiais = request.form.getlist('extra_material[]')
    quantidades = request.form.getlist('extra_qtd[]')

    if not materiais:
        return redirect(url_for('painel_coordenacao'))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for i in range(len(materiais)):
        nome = materiais[i]
        qtd = quantidades[i]
        if nome and qtd:
            cursor.execute("""
                INSERT INTO itens_pedido
                (pedido_id, material_nome, quantidade, quantidade_aprovada, status, adicionado_por)
                VALUES (?, ?, ?, ?, 'Aprovado', 'coordenacao')
            """, (pedido_id, nome, float(qtd), float(qtd)))

    conn.commit()
    conn.close()
    return redirect(url_for('painel_coordenacao'))

@app.route('/exportar_pdf', methods=['POST'])
def exportar_pdf():
    if session.get('user') != 'admin': return redirect(url_for('index'))

    ids_selecionados = request.form.getlist('ids_pedidos')
    if not ids_selecionados: return "Nenhum pedido selecionado."

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    placeholders = ','.join('?' for _ in ids_selecionados)

    # AGORA BUSCA PELO STATUS TAMBÉM PRA NÃO MISTURAR
    query = f"""
        SELECT
            material_nome,
            SUM(quantidade) as total_solicitado,
            SUM(quantidade_aprovada) as total_aprovado,
            status
        FROM itens_pedido
        WHERE pedido_id IN ({placeholders}) AND status != 'Cancelado'
        GROUP BY material_nome, status
        ORDER BY material_nome ASC
    """

    cursor.execute(query, ids_selecionados)
    itens_consolidados = cursor.fetchall()
    conn.close()

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 7, txt="Fundação José Augusto Vieira", ln=True, align='C')
    pdf.cell(0, 5, txt="Relatório Consolidado de Pedidos", ln=True, align='C')
    pdf.set_font("Arial", size=8)

    fuso_br = pytz.timezone('America/Sao_Paulo')
    data_pdf = datetime.now(fuso_br).strftime('%d/%m/%Y %H:%M')
    pdf.cell(0, 10, txt=f"Gerado em: {data_pdf}", ln=True, align='C')
    pdf.ln(5)

    pdf.set_fill_color(200, 220, 255)
    pdf.set_font("Arial", 'B', 12)

    col_mat, col_ped, col_apr = 120, 35, 35
    pdf.cell(col_mat, 10, "Material", border=1, fill=True)
    pdf.cell(col_ped, 10, "Solicitado", border=1, align='C', fill=True)
    pdf.cell(col_apr, 10, "Aprovado", border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Arial", size=10)
    fill = False
    pdf.set_fill_color(240, 240, 240)

    for item in itens_consolidados:
        nome = item[0]
        status_item = item[3]

        try: nome = nome.encode('latin-1', 'replace').decode('latin-1')
        except: pass

        solicitado_fmt = f"{item[1]:g}"
        aprovado_fmt = f"{item[2]:g}"

        # Pega as coordenadas X e Y atuais
        x_inicial = pdf.get_x()
        y_inicial = pdf.get_y()

        pdf.cell(col_mat, 8, nome, border=1, fill=fill)

        # Se O ITEM ESPECÍFICO ESTIVER REPROVADO, FAZ O TRAÇO
        if status_item == 'Reprovado':
            largura_texto = pdf.get_string_width(nome)
            # Adiciona o recuo (+2) para ficar exatamente em cima da palavra e na metade da altura (+4)
            pdf.line(x_inicial + 2, y_inicial + 4, x_inicial + largura_texto + 2, y_inicial + 4)

        pdf.cell(col_ped, 8, solicitado_fmt, border=1, align='C', fill=fill)

        if float(item[2]) > 0:
            pdf.set_font("Arial", 'B', 10)
            pdf.cell(col_apr, 8, aprovado_fmt, border=1, align='C', fill=fill)
            pdf.set_font("Arial", size=10)
        else:
            pdf.cell(col_apr, 8, aprovado_fmt, border=1, align='C', fill=fill)

        pdf.ln()
        fill = not fill

    response = make_response(pdf.output(dest='S').encode('latin-1'))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=lista_consolidada.pdf'
    return response

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

# --- ROTAS PWA (NOVAS) ---
@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/service-worker.js')
def service_worker():
    response = make_response(app.send_static_file('service-worker.js'))
    response.headers['Content-Type'] = 'application/javascript'
    return response

if __name__ == '__main__':
    init_db()
    app.run(debug=True)