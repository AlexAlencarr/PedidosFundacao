from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import json
import os
import unicodedata # Biblioteca para lidar com acentos

app = Flask(__name__)
app.secret_key = 'sua_chave_secreta_aqui'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "escola.db")

# --- LISTA DE PROFESSORAS PERMITIDAS ---
# O sistema usará esses nomes exatos para salvar no banco.
# A senha para todas é '123'.
LISTA_PROFESSORES = [
    "Piedade", "Crislaine", "Ianka", "Ivaneide", "Camila",
    "Talita", "Maiara", "Clara", "Priscilla", "Luciana",
    "Marlise", "Carla", "Aline"
]

# --- FUNÇÃO AUXILIAR PARA REMOVER ACENTOS E MAIÚSCULAS ---
def normalizar_texto(texto):
    if not texto: return ""
    # Transforma "Amanhã" em "amanha"
    return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').lower().strip()

def init_db():
    if not os.path.exists(DB_NAME):
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE materiais (id INTEGER PRIMARY KEY, nome TEXT, unidade TEXT)''')
        cursor.execute('''CREATE TABLE pedidos (
                            id INTEGER PRIMARY KEY,
                            professor TEXT,
                            data_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE itens_pedido (
                            id INTEGER PRIMARY KEY,
                            pedido_id INTEGER,
                            material_nome TEXT,
                            quantidade INTEGER,
                            quantidade_aprovada INTEGER DEFAULT 0,
                            status TEXT DEFAULT 'Pendente',
                            FOREIGN KEY(pedido_id) REFERENCES pedidos(id))''')
        conn.commit()
        conn.close()

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    usuario_input = request.form['usuario']
    senha_input = request.form['senha']
    erro = None

    # 1. Verifica ADMIN
    if usuario_input == 'admin':
        if senha_input == 'admin':
            session['user'] = 'admin'
            return redirect(url_for('painel_coordenacao'))
        else:
            erro = "Senha de administrador incorreta."

    # 2. Verifica PROFESSORES
    else:
        usuario_normalizado = normalizar_texto(usuario_input)

        # Procura se o nome digitado bate com alguém da lista
        professor_encontrado = None
        for prof_real in LISTA_PROFESSORES:
            if normalizar_texto(prof_real) == usuario_normalizado:
                professor_encontrado = prof_real
                break

        if professor_encontrado:
            # Se achou a professora, verifica a senha
            if senha_input == '123':
                session['user'] = professor_encontrado
                return redirect(url_for('painel_professor'))
            else:
                erro = "Senha incorreta."
        else:
            erro = "Usuário não encontrado no sistema."

    # Se chegou aqui, é porque deu algum erro.
    # Recarrega a página de login mostrando a mensagem na tag <small>
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
        cursor.execute("SELECT id, material_nome, quantidade, status, quantidade_aprovada FROM itens_pedido WHERE pedido_id = ?", (ped[0],))
        itens = cursor.fetchall()
        pode_editar = all(item[3] == 'Pendente' for item in itens)
        historico.append({
            'id': ped[0],
            'data': ped[1],
            'itens': itens,
            'pode_editar': pode_editar
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

    cursor.execute("INSERT INTO pedidos (professor) VALUES (?)", (professor,))
    pedido_id = cursor.lastrowid

    for item in itens:
        cursor.execute("INSERT INTO itens_pedido (pedido_id, material_nome, quantidade) VALUES (?, ?, ?)",
                       (pedido_id, item['material'], item['quantidade']))

    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/cancelar_pedido/<int:id>')
def cancelar_pedido(id):
    if 'user' not in session: return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM itens_pedido WHERE pedido_id = ?", (id,))
    conn.execute("DELETE FROM pedidos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/deletar_item/<int:item_id>')
def deletar_item(item_id):
    if 'user' not in session: return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    conn.execute("DELETE FROM itens_pedido WHERE id = ? AND status = 'Pendente'", (item_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/editar_qtd_item', methods=['POST'])
def editar_qtd_item():
    if 'user' not in session: return redirect(url_for('index'))
    item_id = request.form['item_id']
    nova_qtd = request.form['nova_qtd']
    conn = sqlite3.connect(DB_NAME)
    conn.execute("UPDATE itens_pedido SET quantidade = ? WHERE id = ? AND status = 'Pendente'", (nova_qtd, item_id))
    conn.commit()
    conn.close()
    return redirect(url_for('painel_professor'))

@app.route('/coordenacao')
def painel_coordenacao():
    if session.get('user') != 'admin': return redirect(url_for('index'))

    filtro = request.args.get('visualizacao', 'pendentes')

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pedidos ORDER BY id DESC")
    todos_pedidos = cursor.fetchall()

    lista_final = []

    for ped in todos_pedidos:
        cursor.execute("SELECT id, material_nome, quantidade, status, quantidade_aprovada FROM itens_pedido WHERE pedido_id = ?", (ped[0],))
        itens = cursor.fetchall()

        tem_item_pendente = any(item[3] == 'Pendente' for item in itens)
        status_geral = 'Pendente' if tem_item_pendente else 'Concluido'

        if filtro == 'pendentes' and status_geral == 'Pendente':
            lista_final.append({'id': ped[0], 'professor': ped[1], 'data': ped[2], 'itens': itens})
        elif filtro == 'concluidos' and status_geral == 'Concluido':
            lista_final.append({'id': ped[0], 'professor': ped[1], 'data': ped[2], 'itens': itens})

    conn.close()
    return render_template('coordenacao.html', pedidos=lista_final, filtro_atual=filtro)

@app.route('/atualizar_pedido', methods=['POST'])
def atualizar_pedido():
    if session.get('user') != 'admin': return redirect(url_for('index'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for key, value in request.form.items():
        if key.startswith('status_'):
            item_id = key.replace('status_', '')
            status_escolhido = value
            qtd_aprovada_key = f"qtd_aprov_{item_id}"
            qtd_aprovada = request.form.get(qtd_aprovada_key, 0)

            cursor.execute("""
                UPDATE itens_pedido
                SET status = ?, quantidade_aprovada = ?
                WHERE id = ?
            """, (status_escolhido, qtd_aprovada, item_id))

    conn.commit()
    conn.close()
    return redirect(url_for('painel_coordenacao'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)